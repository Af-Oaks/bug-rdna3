#include "harness.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <numeric>
#include <sstream>

#include "fossilize_db.hpp"

// SPIR-V is parsed directly rather than via SPIRV-Cross: the only thing needed
// is the compute local size, which is one opcode. OpExecutionMode <entry>
// LocalSize x y z = opcode 16, mode 17. Pulling in a reflection library for
// three integers would be the larger dependency.
namespace {

constexpr uint32_t SpvOpExecutionMode = 16;
constexpr uint32_t SpvOpExecutionModeId = 331;
constexpr uint32_t SpvExecutionModeLocalSize = 17;
constexpr uint32_t SpvMagic = 0x07230203;

bool spirv_local_size(const uint32_t *words, size_t count, uint32_t out[3])
{
	if (count < 5 || words[0] != SpvMagic)
		return false;
	size_t i = 5;
	while (i < count)
	{
		uint32_t insn = words[i];
		uint32_t len = insn >> 16;
		uint32_t op = insn & 0xffffu;
		if (len == 0 || i + len > count)
			break;
		if ((op == SpvOpExecutionMode || op == SpvOpExecutionModeId) && len >= 6 &&
		    words[i + 2] == SpvExecutionModeLocalSize)
		{
			out[0] = words[i + 3];
			out[1] = words[i + 4];
			out[2] = words[i + 5];
			return true;
		}
		i += len;
	}
	return false;
}

uint64_t median_of(std::vector<uint64_t> v)
{
	if (v.empty())
		return 0;
	std::sort(v.begin(), v.end());
	size_t n = v.size();
	return n % 2 ? v[n / 2] : (v[n / 2 - 1] + v[n / 2]) / 2;
}

} // namespace

const char *status_name(Status s)
{
	switch (s)
	{
	case Status::Ok: return "ok";
	case Status::CreateFailed: return "create_failed";
	case Status::NoDispatch: return "no_dispatch";
	case Status::Unstable: return "unstable";
	}
	return "unknown";
}

// ---------------------------------------------------------------------------
// Fossilize replay: create the real objects, remember what we saw
// ---------------------------------------------------------------------------

class BenchCreator : public Fossilize::StateCreatorInterface
{
public:
	explicit BenchCreator(Harness &h) : h(h) {}

	bool enqueue_create_sampler(Fossilize::Hash, const VkSamplerCreateInfo *ci, VkSampler *out) override
	{
		return vkCreateSampler(h.device, ci, nullptr, out) == VK_SUCCESS;
	}

	bool enqueue_create_descriptor_set_layout(Fossilize::Hash hash,
	                                          const VkDescriptorSetLayoutCreateInfo *ci,
	                                          VkDescriptorSetLayout *out) override
	{
		if (vkCreateDescriptorSetLayout(h.device, ci, nullptr, out) != VK_SUCCESS)
			return false;
		h.set_layouts[hash] = *out;
		// Remember the binding table: dummy resources are built per layout.
		h.set_bindings[hash].assign(ci->pBindings, ci->pBindings + ci->bindingCount);
		handle_to_hash[*out] = hash;
		return true;
	}

	bool enqueue_create_pipeline_layout(Fossilize::Hash, const VkPipelineLayoutCreateInfo *ci,
	                                    VkPipelineLayout *out) override
	{
		if (vkCreatePipelineLayout(h.device, ci, nullptr, out) != VK_SUCCESS)
			return false;
		std::vector<Fossilize::Hash> sets;
		for (uint32_t i = 0; i < ci->setLayoutCount; i++)
		{
			auto it = handle_to_hash.find(ci->pSetLayouts[i]);
			sets.push_back(it == handle_to_hash.end() ? 0 : it->second);
		}
		h.layout_sets[*out] = std::move(sets);
		uint32_t pc = 0;
		for (uint32_t i = 0; i < ci->pushConstantRangeCount; i++)
			pc = std::max(pc, ci->pPushConstantRanges[i].offset + ci->pPushConstantRanges[i].size);
		push_bytes[*out] = pc;
		return true;
	}

	bool enqueue_create_shader_module(Fossilize::Hash hash, const VkShaderModuleCreateInfo *ci,
	                                  VkShaderModule *out) override
	{
		uint32_t ls[3] = { 1, 1, 1 };
		if (ci->pCode && ci->codeSize >= 20 &&
		    spirv_local_size(ci->pCode, ci->codeSize / 4, ls))
		{
			h.module_local_size[hash] = (ls[0] & 0x3ff) | ((ls[1] & 0x3ff) << 10) | ((ls[2] & 0x3ff) << 20);
		}
		if (vkCreateShaderModule(h.device, ci, nullptr, out) != VK_SUCCESS)
			return false;
		module_of[*out] = hash;
		return true;
	}

	bool enqueue_create_render_pass(Fossilize::Hash, const VkRenderPassCreateInfo *ci,
	                               VkRenderPass *out) override
	{
		return vkCreateRenderPass(h.device, ci, nullptr, out) == VK_SUCCESS;
	}
	bool enqueue_create_render_pass2(Fossilize::Hash, const VkRenderPassCreateInfo2 *ci,
	                                VkRenderPass *out) override
	{
		return vkCreateRenderPass2(h.device, ci, nullptr, out) == VK_SUCCESS;
	}

	bool enqueue_create_compute_pipeline(Fossilize::Hash hash, const VkComputePipelineCreateInfo *ci,
	                                     VkPipeline *out) override
	{
		if (!h.wanted.empty() && !h.wanted.count(hash))
			return true;   // not in the corpus; skip without failing the replay
		if (h.cfg.limit && h.work.size() >= h.cfg.limit)
			return true;

		PipelineEntry e;
		e.hash = hash;
		e.layout = ci->layout;

		auto mit = module_of.find(ci->stage.module);
		if (mit != module_of.end())
		{
			auto lit = h.module_local_size.find(mit->second);
			if (lit != h.module_local_size.end())
			{
				e.local_size[0] = lit->second & 0x3ff;
				e.local_size[1] = (lit->second >> 10) & 0x3ff;
				e.local_size[2] = (lit->second >> 20) & 0x3ff;
			}
		}
		auto sit = h.layout_sets.find(ci->layout);
		if (sit != h.layout_sets.end())
			e.set_layouts = sit->second;
		auto pit = push_bytes.find(ci->layout);
		e.push_constant_bytes = pit == push_bytes.end() ? 0 : pit->second;

		if (vkCreateComputePipelines(h.device, VK_NULL_HANDLE, 1, ci, nullptr, out) != VK_SUCCESS)
		{
			// A compiler that refuses a pipeline is DATA. Record it and move on.
			e.status = Status::CreateFailed;
			h.created_failed++;
			h.work.push_back(e);
			return true;
		}
		e.pipeline = *out;
		h.work.push_back(e);
		return true;
	}

	// Stage 1 is compute-only: graphics needs render targets, vertex state and
	// attachment formats, which is Stage 2. Returning true keeps the replay
	// going rather than aborting the whole database.
	bool enqueue_create_graphics_pipeline(Fossilize::Hash, const VkGraphicsPipelineCreateInfo *,
	                                      VkPipeline *) override { return true; }
	bool enqueue_create_raytracing_pipeline(Fossilize::Hash, const VkRayTracingPipelineCreateInfoKHR *,
	                                        VkPipeline *) override { return true; }

private:
	Harness &h;
	std::unordered_map<VkDescriptorSetLayout, Fossilize::Hash> handle_to_hash;
	std::unordered_map<VkShaderModule, Fossilize::Hash> module_of;
	std::unordered_map<VkPipelineLayout, uint32_t> push_bytes;
};

// ---------------------------------------------------------------------------
// device
// ---------------------------------------------------------------------------

bool Harness::init(const BenchConfig &c)
{
	cfg = c;
	if (volkInitialize() != VK_SUCCESS)
	{
		err = "volkInitialize failed -- no Vulkan loader?";
		return false;
	}
	return create_device() && create_arena();
}

bool Harness::create_device()
{
	VkApplicationInfo app{ VK_STRUCTURE_TYPE_APPLICATION_INFO };
	app.pApplicationName = "tcc-shaderbench";
	app.apiVersion = VK_API_VERSION_1_3;

	VkInstanceCreateInfo ici{ VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO };
	ici.pApplicationInfo = &app;
	if (vkCreateInstance(&ici, nullptr, &instance) != VK_SUCCESS)
	{
		err = "vkCreateInstance failed";
		return false;
	}
	volkLoadInstance(instance);

	uint32_t n = 0;
	vkEnumeratePhysicalDevices(instance, &n, nullptr);
	if (!n)
	{
		err = "no Vulkan physical device (is VK_ICD_FILENAMES pointing at a real ICD?)";
		return false;
	}
	std::vector<VkPhysicalDevice> gpus(n);
	vkEnumeratePhysicalDevices(instance, &n, gpus.data());
	gpu = gpus[0];

	VkPhysicalDeviceDriverProperties drv{ VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES };
	VkPhysicalDeviceProperties2 props{ VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2 };
	props.pNext = &drv;
	vkGetPhysicalDeviceProperties2(gpu, &props);
	device_name = props.properties.deviceName;
	driver_info = drv.driverInfo;
	timestamp_period_ns = props.properties.limits.timestampPeriod;

	uint32_t qn = 0;
	vkGetPhysicalDeviceQueueFamilyProperties(gpu, &qn, nullptr);
	std::vector<VkQueueFamilyProperties> qf(qn);
	vkGetPhysicalDeviceQueueFamilyProperties(gpu, &qn, qf.data());
	bool found = false;
	for (uint32_t i = 0; i < qn; i++)
		if (qf[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { queue_family = i; found = true; break; }
	if (!found)
	{
		err = "no compute queue family";
		return false;
	}

	float prio = 1.0f;
	VkDeviceQueueCreateInfo q{ VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO };
	q.queueFamilyIndex = queue_family;
	q.queueCount = 1;
	q.pQueuePriorities = &prio;

	// robustness2 + nullDescriptor is what makes a garbage descriptor index
	// survivable; bufferDeviceAddress is what makes the arena trick possible.
	// Both apply identically to every compiler build, so they cancel in an A/B.
	// vkd3d-proton lowers the D3D12 descriptor heap into a MUTABLE descriptor
	// array of ~1,000,000 entries. Without this feature the layout cannot even
	// be allocated from, so it is not optional for DX12 titles.
	VkPhysicalDeviceMutableDescriptorTypeFeaturesEXT mut{
		VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_MUTABLE_DESCRIPTOR_TYPE_FEATURES_EXT };
	mut.mutableDescriptorType = VK_TRUE;

	VkPhysicalDeviceRobustness2FeaturesEXT rob{ VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT };
	rob.pNext = &mut;
	rob.robustBufferAccess2 = VK_TRUE;
	rob.robustImageAccess2 = VK_TRUE;
	rob.nullDescriptor = VK_TRUE;

	VkPhysicalDeviceVulkan12Features v12{ VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES };
	v12.pNext = &rob;
	v12.bufferDeviceAddress = VK_TRUE;
	v12.descriptorIndexing = VK_TRUE;
	v12.runtimeDescriptorArray = VK_TRUE;
	v12.descriptorBindingPartiallyBound = VK_TRUE;
	v12.descriptorBindingVariableDescriptorCount = VK_TRUE;
	v12.shaderSampledImageArrayNonUniformIndexing = VK_TRUE;
	v12.shaderStorageBufferArrayNonUniformIndexing = VK_TRUE;
	v12.scalarBlockLayout = VK_TRUE;

	VkPhysicalDeviceVulkan13Features v13{ VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES };
	v13.pNext = &v12;
	v13.dynamicRendering = VK_TRUE;
	v13.maintenance4 = VK_TRUE;

	VkPhysicalDeviceFeatures2 f2{ VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2 };
	f2.pNext = &v13;
	f2.features.robustBufferAccess = VK_TRUE;
	f2.features.shaderInt64 = VK_TRUE;

	const char *exts[] = {
		VK_EXT_ROBUSTNESS_2_EXTENSION_NAME,
		VK_EXT_MUTABLE_DESCRIPTOR_TYPE_EXTENSION_NAME,
		VK_EXT_DESCRIPTOR_INDEXING_EXTENSION_NAME,
	};

	VkDeviceCreateInfo dci{ VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO };
	dci.pNext = &f2;
	dci.queueCreateInfoCount = 1;
	dci.pQueueCreateInfos = &q;
	dci.enabledExtensionCount = uint32_t(sizeof(exts) / sizeof(exts[0]));
	dci.ppEnabledExtensionNames = exts;

	if (vkCreateDevice(gpu, &dci, nullptr, &device) != VK_SUCCESS)
	{
		err = "vkCreateDevice failed (robustness2 / bufferDeviceAddress unsupported?)";
		return false;
	}
	volkLoadDevice(device);
	vkGetDeviceQueue(device, queue_family, 0, &queue);

	VkCommandPoolCreateInfo cp{ VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO };
	cp.queueFamilyIndex = queue_family;
	cp.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
	vkCreateCommandPool(device, &cp, nullptr, &cmd_pool);

	VkQueryPoolCreateInfo qp{ VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO };
	qp.queryType = VK_QUERY_TYPE_TIMESTAMP;
	qp.queryCount = 2;
	vkCreateQueryPool(device, &qp, nullptr, &query_pool);

	// No global descriptor pool: pools are created per layout, sized from that
	// layout's own bindings. A fixed global pool cannot serve a 1,000,000-entry
	// bindless heap and a 4-entry uniform set from the same budget.
	return true;
}

static uint32_t find_mem(VkPhysicalDevice gpu, uint32_t bits, VkMemoryPropertyFlags want)
{
	VkPhysicalDeviceMemoryProperties mp{};
	vkGetPhysicalDeviceMemoryProperties(gpu, &mp);
	for (uint32_t i = 0; i < mp.memoryTypeCount; i++)
		if ((bits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & want) == want)
			return i;
	return UINT32_MAX;
}

bool Harness::create_arena()
{
	VkBufferCreateInfo bi{ VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO };
	bi.size = cfg.arena_bytes;
	bi.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_UNIFORM_BUFFER_BIT |
	           VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_SHADER_DEVICE_ADDRESS_BIT |
	           VK_BUFFER_USAGE_UNIFORM_TEXEL_BUFFER_BIT | VK_BUFFER_USAGE_STORAGE_TEXEL_BUFFER_BIT;
	if (vkCreateBuffer(device, &bi, nullptr, &arena) != VK_SUCCESS)
	{
		err = "arena vkCreateBuffer failed";
		return false;
	}
	VkMemoryRequirements req{};
	vkGetBufferMemoryRequirements(device, arena, &req);

	VkMemoryAllocateFlagsInfo fi{ VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_FLAGS_INFO };
	fi.flags = VK_MEMORY_ALLOCATE_DEVICE_ADDRESS_BIT;
	VkMemoryAllocateInfo ai{ VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO };
	ai.pNext = &fi;
	ai.allocationSize = req.size;
	ai.memoryTypeIndex = find_mem(gpu, req.memoryTypeBits,
	                              VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
	if (ai.memoryTypeIndex == UINT32_MAX)
	{
		err = "no host-visible memory type for the arena";
		return false;
	}
	if (vkAllocateMemory(device, &ai, nullptr, &arena_mem) != VK_SUCCESS)
	{
		err = "arena vkAllocateMemory failed (try a smaller --arena-mb)";
		return false;
	}
	vkBindBufferMemory(device, arena, arena_mem, 0);

	VkBufferDeviceAddressInfo bda{ VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO };
	bda.buffer = arena;
	VkDeviceAddress base = vkGetBufferDeviceAddress(device, &bda);
	// Aim at the MIDDLE so a shader that adds OR subtracts an offset from a
	// pointer it read still lands inside the allocation.
	arena_addr = base + cfg.arena_bytes / 2;

	// Fill the whole arena with that address repeated every 8 bytes: any 64-bit
	// word a shader dereferences as a pointer is then valid wherever it read it.
	void *mapped = nullptr;
	if (vkMapMemory(device, arena_mem, 0, VK_WHOLE_SIZE, 0, &mapped) == VK_SUCCESS)
	{
		auto *p = static_cast<uint64_t *>(mapped);
		const uint64_t pattern = uint64_t(arena_addr);
		for (uint64_t i = 0; i < cfg.arena_bytes / 8; i++)
			p[i] = pattern;
		vkUnmapMemory(device, arena_mem);
	}

	// One dummy image, written into every image descriptor slot.
	VkImageCreateInfo ii{ VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO };
	ii.imageType = VK_IMAGE_TYPE_2D;
	ii.format = VK_FORMAT_R8G8B8A8_UNORM;
	ii.extent = { 64, 64, 1 };
	ii.mipLevels = 1;
	ii.arrayLayers = 1;
	ii.samples = VK_SAMPLE_COUNT_1_BIT;
	ii.tiling = VK_IMAGE_TILING_OPTIMAL;
	ii.usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
	ii.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
	if (vkCreateImage(device, &ii, nullptr, &dummy_image) != VK_SUCCESS)
	{
		err = "dummy image creation failed";
		return false;
	}
	VkMemoryRequirements ireq{};
	vkGetImageMemoryRequirements(device, dummy_image, &ireq);
	VkMemoryAllocateInfo iai{ VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO };
	iai.allocationSize = ireq.size;
	iai.memoryTypeIndex = find_mem(gpu, ireq.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
	vkAllocateMemory(device, &iai, nullptr, &dummy_image_mem);
	vkBindImageMemory(device, dummy_image, dummy_image_mem, 0);

	VkImageViewCreateInfo vi{ VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO };
	vi.image = dummy_image;
	vi.viewType = VK_IMAGE_VIEW_TYPE_2D;
	vi.format = ii.format;
	vi.subresourceRange = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 };
	vkCreateImageView(device, &vi, nullptr, &dummy_view);

	VkSamplerCreateInfo si{ VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO };
	si.magFilter = si.minFilter = VK_FILTER_LINEAR;
	si.addressModeU = si.addressModeV = si.addressModeW = VK_SAMPLER_ADDRESS_MODE_REPEAT;
	si.maxLod = VK_LOD_CLAMP_NONE;
	vkCreateSampler(device, &si, nullptr, &dummy_sampler);

	// Transition the image once so descriptors referencing it are legal.
	VkCommandBufferAllocateInfo cbi{ VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO };
	cbi.commandPool = cmd_pool;
	cbi.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
	cbi.commandBufferCount = 1;
	VkCommandBuffer cb;
	vkAllocateCommandBuffers(device, &cbi, &cb);
	VkCommandBufferBeginInfo bbi{ VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
	bbi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
	vkBeginCommandBuffer(cb, &bbi);
	VkImageMemoryBarrier bar{ VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER };
	bar.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
	bar.newLayout = VK_IMAGE_LAYOUT_GENERAL;
	bar.image = dummy_image;
	bar.subresourceRange = vi.subresourceRange;
	bar.srcAccessMask = 0;
	bar.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT;
	vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
	                     0, 0, nullptr, 0, nullptr, 1, &bar);
	vkEndCommandBuffer(cb);
	VkSubmitInfo sub{ VK_STRUCTURE_TYPE_SUBMIT_INFO };
	sub.commandBufferCount = 1;
	sub.pCommandBuffers = &cb;
	vkQueueSubmit(queue, 1, &sub, VK_NULL_HANDLE);
	vkQueueWaitIdle(queue);
	vkFreeCommandBuffers(device, cmd_pool, 1, &cb);
	return true;
}

// ---------------------------------------------------------------------------
// dummy descriptor sets, one per distinct layout
// ---------------------------------------------------------------------------

VkDescriptorSet Harness::dummy_set_for(Fossilize::Hash layout_hash)
{
	auto it = dummy_sets.find(layout_hash);
	if (it != dummy_sets.end())
		return it->second;

	auto lit = set_layouts.find(layout_hash);
	if (lit == set_layouts.end())
		return VK_NULL_HANDLE;

	const auto &bindings = set_bindings[layout_hash];

	// Size a dedicated pool from THIS layout's bindings. vkd3d-proton's
	// descriptor heap is one binding with descriptorCount == 1,000,000; a
	// shared pool with a fixed budget returns OUT_OF_POOL_MEMORY on it, which
	// is what the first spike hit.
	std::unordered_map<int, uint32_t> need;
	for (const auto &b : bindings)
		if (b.descriptorCount)
			need[int(b.descriptorType)] += b.descriptorCount;
	if (need.empty())
		need[int(VK_DESCRIPTOR_TYPE_STORAGE_BUFFER)] = 1;

	std::vector<VkDescriptorPoolSize> sizes;
	sizes.reserve(need.size());
	for (auto &kv : need)
		sizes.push_back({ VkDescriptorType(kv.first), kv.second });

	VkDescriptorPoolCreateInfo dp{ VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
	dp.maxSets = 1;
	dp.poolSizeCount = uint32_t(sizes.size());
	dp.pPoolSizes = sizes.data();
	// The layout may declare UPDATE_AFTER_BIND; the pool must agree or
	// allocation fails. Setting it unconditionally is harmless otherwise.
	dp.flags = VK_DESCRIPTOR_POOL_CREATE_UPDATE_AFTER_BIND_BIT;

	VkDescriptorPool pool = VK_NULL_HANDLE;
	if (vkCreateDescriptorPool(device, &dp, nullptr, &pool) != VK_SUCCESS)
	{
		dp.flags = 0;
		if (vkCreateDescriptorPool(device, &dp, nullptr, &pool) != VK_SUCCESS)
		{
			dummy_sets[layout_hash] = VK_NULL_HANDLE;
			return VK_NULL_HANDLE;
		}
	}
	layout_pools.push_back(pool);

	VkDescriptorSetAllocateInfo ai{ VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
	ai.descriptorPool = pool;
	ai.descriptorSetCount = 1;
	ai.pSetLayouts = &lit->second;

	// A variable-count binding must be told how many descriptors to allocate.
	uint32_t variable_count = 0;
	for (const auto &b : bindings)
		variable_count = std::max(variable_count, b.descriptorCount);
	VkDescriptorSetVariableDescriptorCountAllocateInfo vc{
		VK_STRUCTURE_TYPE_DESCRIPTOR_SET_VARIABLE_DESCRIPTOR_COUNT_ALLOCATE_INFO };
	vc.descriptorSetCount = 1;
	vc.pDescriptorCounts = &variable_count;
	ai.pNext = &vc;

	VkDescriptorSet set = VK_NULL_HANDLE;
	VkResult ar = vkAllocateDescriptorSets(device, &ai, &set);
	if (ar != VK_SUCCESS)
	{
		ai.pNext = nullptr;   // layout may not declare a variable-count binding
		ar = vkAllocateDescriptorSets(device, &ai, &set);
	}
	if (ar != VK_SUCCESS)
	{
		std::fprintf(stderr, "  [desc] layout %016llx alloc failed (VkResult %d)\n",
		             (unsigned long long)layout_hash, int(ar));
		dummy_sets[layout_hash] = VK_NULL_HANDLE;
		return VK_NULL_HANDLE;
	}

	// Write dummies. Huge bindless arrays are written up to a cap: beyond it we
	// rely on robustness2 nullDescriptor, which makes an unwritten slot read as
	// zero instead of faulting. Writing a million identical descriptors costs
	// real time and buys nothing a null descriptor does not already give us.
	constexpr uint32_t WRITE_CAP = 4096;
	std::vector<VkWriteDescriptorSet> writes;
	std::vector<std::vector<VkDescriptorBufferInfo>> buf_store;
	std::vector<std::vector<VkDescriptorImageInfo>> img_store;
	buf_store.reserve(bindings.size());
	img_store.reserve(bindings.size());

	for (const auto &b : bindings)
	{
		if (!b.descriptorCount)
			continue;
		const uint32_t n = std::min(b.descriptorCount, WRITE_CAP);

		VkWriteDescriptorSet w{ VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET };
		w.dstSet = set;
		w.dstBinding = b.binding;
		w.descriptorCount = n;
		w.descriptorType = b.descriptorType;

		switch (b.descriptorType)
		{
		case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER:
		case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER:
		case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC:
		case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC:
			buf_store.emplace_back(n, VkDescriptorBufferInfo{ arena, 0, VK_WHOLE_SIZE });
			w.pBufferInfo = buf_store.back().data();
			break;
		case VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE:
		case VK_DESCRIPTOR_TYPE_STORAGE_IMAGE:
		case VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER:
		case VK_DESCRIPTOR_TYPE_SAMPLER:
			img_store.emplace_back(n, VkDescriptorImageInfo{ dummy_sampler, dummy_view,
			                                                 VK_IMAGE_LAYOUT_GENERAL });
			w.pImageInfo = img_store.back().data();
			break;
		default:
			// MUTABLE and texel-buffer descriptors have no single correct dummy;
			// nullDescriptor makes them safe to read unwritten.
			continue;
		}
		writes.push_back(w);
	}
	if (!writes.empty())
		vkUpdateDescriptorSets(device, uint32_t(writes.size()), writes.data(), 0, nullptr);

	dummy_sets[layout_hash] = set;
	return set;
}

// ---------------------------------------------------------------------------
// load
// ---------------------------------------------------------------------------

bool Harness::load(const std::string &foz_path, const std::string &hashes_path)
{
	if (!hashes_path.empty())
	{
		std::ifstream in(hashes_path);
		if (!in)
		{
			err = "cannot read hash list: " + hashes_path;
			return false;
		}
		std::string line;
		while (std::getline(in, line))
		{
			while (!line.empty() && (line.back() == '\n' || line.back() == '\r' || line.back() == ' '))
				line.pop_back();
			if (!line.empty())
				wanted.insert(std::strtoull(line.c_str(), nullptr, 16));
		}
	}

	auto *db = Fossilize::create_database(foz_path.c_str(), Fossilize::DatabaseMode::ReadOnly);
	if (!db || !db->prepare())
	{
		err = "cannot open Fossilize database: " + foz_path;
		return false;
	}

	BenchCreator creator(*this);
	Fossilize::StateReplayer replayer;

	static const Fossilize::ResourceTag order[] = {
		Fossilize::RESOURCE_APPLICATION_INFO, Fossilize::RESOURCE_SAMPLER,
		Fossilize::RESOURCE_DESCRIPTOR_SET_LAYOUT, Fossilize::RESOURCE_PIPELINE_LAYOUT,
		Fossilize::RESOURCE_SHADER_MODULE, Fossilize::RESOURCE_RENDER_PASS,
		Fossilize::RESOURCE_COMPUTE_PIPELINE,
	};

	std::vector<uint8_t> buffer;
	for (auto tag : order)
	{
		size_t count = 0;
		if (!db->get_hash_list_for_resource_tag(tag, &count, nullptr))
			continue;
		std::vector<Fossilize::Hash> hashes(count);
		if (!db->get_hash_list_for_resource_tag(tag, &count, hashes.data()))
			continue;
		for (auto h : hashes)
		{
			size_t size = 0;
			if (!db->read_entry(tag, h, &size, nullptr, 0))
				continue;
			buffer.resize(size);
			if (!db->read_entry(tag, h, &size, buffer.data(), 0))
				continue;
			if (!replayer.parse(creator, db, buffer.data(), size))
				continue;   // a malformed blob is skipped, not fatal
			if (cfg.limit && work.size() >= cfg.limit && tag == Fossilize::RESOURCE_COMPUTE_PIPELINE)
				break;
		}
		creator.notify_replayed_resources_for_type();
	}
	delete db;

	if (work.empty())
	{
		err = "no compute pipelines found (Stage 1 is compute-only; a graphics-heavy "
		      "database will legitimately yield none)";
		return false;
	}
	return true;
}

void Harness::compute_groups(const PipelineEntry &e, uint32_t out[3]) const
{
	// Fixed invocation budget divided by the shader's own workgroup size, so a
	// 64-thread and a 256-thread shader do the same total work and their times
	// are comparable.
	uint64_t per_group = uint64_t(e.local_size[0]) * e.local_size[1] * e.local_size[2];
	if (!per_group)
		per_group = 1;
	uint64_t groups = cfg.invocation_budget / per_group;
	if (!groups)
		groups = 1;
	if (groups > 65535)
		groups = 65535;
	out[0] = uint32_t(groups);
	out[1] = 1;
	out[2] = 1;
}

// ---------------------------------------------------------------------------
// measure
// ---------------------------------------------------------------------------

bool Harness::measure(PipelineEntry &e, Measurement &m)
{
	m.hash = e.hash;
	if (e.status == Status::CreateFailed || e.pipeline == VK_NULL_HANDLE)
	{
		m.status = Status::CreateFailed;
		return false;
	}
	compute_groups(e, m.groups);

	std::vector<VkDescriptorSet> sets;
	for (auto h : e.set_layouts)
	{
		VkDescriptorSet s = dummy_set_for(h);
		if (s == VK_NULL_HANDLE)
		{
			m.status = Status::NoDispatch;
			return false;
		}
		sets.push_back(s);
	}

	VkCommandBufferAllocateInfo cbi{ VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO };
	cbi.commandPool = cmd_pool;
	cbi.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
	cbi.commandBufferCount = 1;
	VkCommandBuffer cb;
	vkAllocateCommandBuffers(device, &cbi, &cb);

	std::vector<uint8_t> push(e.push_constant_bytes, 0);
	// 8-byte-aligned push-constant slots also get the arena address: vkd3d
	// passes root descriptors as push constants, and those are pointers too.
	for (size_t i = 0; i + 8 <= push.size(); i += 8)
		std::memcpy(push.data() + i, &arena_addr, 8);

	auto record = [&](uint32_t iters, bool timed) {
		VkCommandBufferBeginInfo bbi{ VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
		bbi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
		vkBeginCommandBuffer(cb, &bbi);
		if (timed)
		{
			vkCmdResetQueryPool(cb, query_pool, 0, 2);
			vkCmdWriteTimestamp(cb, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, query_pool, 0);
		}
		vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, e.pipeline);
		if (!sets.empty())
			vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, e.layout, 0,
			                        uint32_t(sets.size()), sets.data(), 0, nullptr);
		if (!push.empty())
			vkCmdPushConstants(cb, e.layout, VK_SHADER_STAGE_COMPUTE_BIT, 0,
			                   uint32_t(push.size()), push.data());
		for (uint32_t i = 0; i < iters; i++)
		{
			vkCmdDispatch(cb, m.groups[0], m.groups[1], m.groups[2]);
			// Serialize so the dispatches do not overlap: overlapping would
			// measure the scheduler's packing, not the shader.
			VkMemoryBarrier mb{ VK_STRUCTURE_TYPE_MEMORY_BARRIER };
			mb.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT;
			mb.dstAccessMask = VK_ACCESS_SHADER_READ_BIT | VK_ACCESS_SHADER_WRITE_BIT;
			vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT,
			                     VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 1, &mb, 0, nullptr, 0, nullptr);
		}
		if (timed)
			vkCmdWriteTimestamp(cb, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, query_pool, 1);
		vkEndCommandBuffer(cb);
	};

	auto submit = [&]() -> bool {
		VkSubmitInfo sub{ VK_STRUCTURE_TYPE_SUBMIT_INFO };
		sub.commandBufferCount = 1;
		sub.pCommandBuffers = &cb;
		if (vkQueueSubmit(queue, 1, &sub, VK_NULL_HANDLE) != VK_SUCCESS)
			return false;
		return vkQueueWaitIdle(queue) == VK_SUCCESS;
	};

	if (cfg.warmup_iterations)
	{
		record(cfg.warmup_iterations, false);
		if (!submit())
		{
			m.status = Status::NoDispatch;
			vkFreeCommandBuffers(device, cmd_pool, 1, &cb);
			return false;
		}
	}

	for (uint32_t r = 0; r < cfg.repetitions; r++)
	{
		record(cfg.iterations, true);
		if (!submit())
		{
			m.status = Status::NoDispatch;
			vkFreeCommandBuffers(device, cmd_pool, 1, &cb);
			return false;
		}
		uint64_t ts[2] = { 0, 0 };
		vkGetQueryPoolResults(device, query_pool, 0, 2, sizeof(ts), ts, sizeof(uint64_t),
		                      VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
		double total_ns = double(ts[1] - ts[0]) * timestamp_period_ns;
		m.reps_ns.push_back(uint64_t(total_ns / cfg.iterations));
	}
	vkFreeCommandBuffers(device, cmd_pool, 1, &cb);

	// L2 reduction: drop the slowest `trim_worst`, mean the rest. One-sided by
	// design -- it removes upward noise only, so it biases the ABSOLUTE number
	// optimistically. That is acceptable because the identical trim is applied
	// to both compilers and cancels in the delta. It is NOT acceptable to quote
	// a trimmed mean as "this shader costs X ns".
	std::vector<uint64_t> sorted = m.reps_ns;
	std::sort(sorted.begin(), sorted.end());
	for (uint32_t i = 0; i < cfg.trim_worst && sorted.size() > 1; i++)
	{
		m.discarded_ns.push_back(sorted.back());
		sorted.pop_back();
	}
	double sum = 0.0;
	for (auto v : sorted)
		sum += double(v);
	m.mean_ns = sorted.empty() ? 0.0 : sum / sorted.size();
	m.median_ns = double(median_of(sorted));

	double var = 0.0;
	for (auto v : sorted)
		var += (double(v) - m.mean_ns) * (double(v) - m.mean_ns);
	double sd = sorted.empty() ? 0.0 : std::sqrt(var / sorted.size());
	m.cv_pct = m.mean_ns > 0.0 ? 100.0 * sd / m.mean_ns : 0.0;
	m.stable = m.cv_pct <= cfg.max_cv_pct;
	m.status = m.stable ? Status::Ok : Status::Unstable;
	return true;
}

void Harness::run()
{
	results.reserve(work.size());
	size_t done = 0;
	for (auto &e : work)
	{
		Measurement m;
		measure(e, m);
		results.push_back(std::move(m));
		if (++done % 25 == 0)
			std::fprintf(stderr, "  %zu / %zu pipelines\n", done, work.size());
	}
}

bool Harness::any_ok() const
{
	for (const auto &m : results)
		if (m.status == Status::Ok)
			return true;
	return false;
}

void Harness::print_listing() const
{
	for (const auto &e : work)
		std::printf("%016llx  local_size=%ux%ux%u  sets=%zu  %s\n",
		            (unsigned long long)e.hash, e.local_size[0], e.local_size[1], e.local_size[2],
		            e.set_layouts.size(), status_name(e.status));
	std::fprintf(stderr, "%zu pipeline(s), %u failed to create\n", work.size(), created_failed);
}

void Harness::write_report(const std::string &out_path) const
{
	std::ostringstream o;
	size_t ok = 0, unstable = 0, failed = 0, nodisp = 0;
	for (const auto &m : results)
	{
		switch (m.status)
		{
		case Status::Ok: ok++; break;
		case Status::Unstable: unstable++; break;
		case Status::CreateFailed: failed++; break;
		case Status::NoDispatch: nodisp++; break;
		}
	}

	o << "{\n";
	o << "  \"device\": \"" << device_name << "\",\n";
	o << "  \"driver_info\": \"" << driver_info << "\",\n";
	o << "  \"timestamp_period_ns\": " << timestamp_period_ns << ",\n";
	o << "  \"config\": {\"warmup\":" << cfg.warmup_iterations
	  << ",\"iterations\":" << cfg.iterations
	  << ",\"repetitions\":" << cfg.repetitions
	  << ",\"trim_worst\":" << cfg.trim_worst
	  << ",\"max_cv_pct\":" << cfg.max_cv_pct
	  << ",\"invocation_budget\":" << cfg.invocation_budget
	  << ",\"arena_bytes\":" << cfg.arena_bytes << "},\n";
	o << "  \"coverage\": {\"pipelines\":" << results.size()
	  << ",\"ok\":" << ok << ",\"unstable\":" << unstable
	  << ",\"create_failed\":" << failed << ",\"no_dispatch\":" << nodisp << "},\n";
	o << "  \"caveat\": \"Synthetic inputs. Absolute nanoseconds are not the game's "
	     "nanoseconds; only the relative delta between two compilers on the same shader "
	     "is meaningful. The trimmed mean is one-sided and cancels only in a delta.\",\n";
	o << "  \"pipelines\": [\n";
	for (size_t i = 0; i < results.size(); i++)
	{
		const auto &m = results[i];
		char hb[32];
		std::snprintf(hb, sizeof(hb), "%016llx", (unsigned long long)m.hash);
		o << "    {\"hash\":\"" << hb << "\",\"status\":\"" << status_name(m.status) << "\"";
		o << ",\"groups\":[" << m.groups[0] << "," << m.groups[1] << "," << m.groups[2] << "]";
		o << ",\"reps_ns\":[";
		for (size_t k = 0; k < m.reps_ns.size(); k++)
			o << (k ? "," : "") << m.reps_ns[k];
		o << "],\"discarded_ns\":[";
		for (size_t k = 0; k < m.discarded_ns.size(); k++)
			o << (k ? "," : "") << m.discarded_ns[k];
		o << "],\"mean_ns\":" << m.mean_ns
		  << ",\"median_ns\":" << m.median_ns
		  << ",\"cv_pct\":" << m.cv_pct
		  << ",\"stable\":" << (m.stable ? "true" : "false") << "}";
		o << (i + 1 < results.size() ? ",\n" : "\n");
	}
	o << "  ]\n}\n";

	if (out_path.empty())
		std::fputs(o.str().c_str(), stdout);
	else
	{
		std::ofstream f(out_path);
		f << o.str();
	}
	std::fprintf(stderr, "coverage: %zu ok / %zu unstable / %zu create_failed / %zu no_dispatch"
	                     " of %zu\n", ok, unstable, failed, nodisp, results.size());
}

Harness::~Harness()
{
	if (device)
	{
		vkDeviceWaitIdle(device);
		if (dummy_sampler) vkDestroySampler(device, dummy_sampler, nullptr);
		if (dummy_view) vkDestroyImageView(device, dummy_view, nullptr);
		if (dummy_image) vkDestroyImage(device, dummy_image, nullptr);
		if (dummy_image_mem) vkFreeMemory(device, dummy_image_mem, nullptr);
		if (arena) vkDestroyBuffer(device, arena, nullptr);
		if (arena_mem) vkFreeMemory(device, arena_mem, nullptr);
		for (auto p : layout_pools) vkDestroyDescriptorPool(device, p, nullptr);
		if (query_pool) vkDestroyQueryPool(device, query_pool, nullptr);
		if (cmd_pool) vkDestroyCommandPool(device, cmd_pool, nullptr);
		vkDestroyDevice(device, nullptr);
	}
	if (instance)
		vkDestroyInstance(instance, nullptr);
}
