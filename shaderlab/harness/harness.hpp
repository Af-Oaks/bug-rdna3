#pragma once

// The benchmark harness. One class, because the pieces are not independently
// useful: the resource pool only makes sense for layouts this replay saw, and
// the timing only makes sense for pipelines this replay created.

#include <cstdint>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "volk.h"
#include "fossilize.hpp"

struct BenchConfig
{
	uint32_t warmup_iterations = 50;
	uint32_t iterations = 200;      // L1: dispatches inside one timed batch
	uint32_t repetitions = 4;       // L2: timed batches per pipeline
	uint32_t trim_worst = 1;        // L2: slowest batches discarded
	double   max_cv_pct = 2.0;      // stability gate over the kept batches
	uint64_t invocation_budget = 1ull << 20;  // fixed thread count per shader
	uint64_t arena_bytes = 256ull * 1024 * 1024;
	uint64_t limit = 0;             // 0 = every pipeline
};

// Never collapses to a bool. A pipeline the compiler refused is a finding and
// must stay distinguishable from one that ran and was merely slow.
enum class Status
{
	Ok,
	CreateFailed,
	NoDispatch,     // created, but we could not derive a dispatch for it
	Unstable,       // ran, but CV over kept repetitions exceeded the gate
};

const char *status_name(Status s);

struct PipelineEntry
{
	Fossilize::Hash hash = 0;
	VkPipeline pipeline = VK_NULL_HANDLE;
	VkPipelineLayout layout = VK_NULL_HANDLE;
	uint32_t local_size[3] = { 1, 1, 1 };
	std::vector<Fossilize::Hash> set_layouts;
	uint32_t push_constant_bytes = 0;
	Status status = Status::Ok;
};

struct Measurement
{
	Fossilize::Hash hash = 0;
	std::vector<uint64_t> reps_ns;       // every repetition, in run order
	std::vector<uint64_t> discarded_ns;  // what the trim removed
	double mean_ns = 0.0;                // trimmed mean of the kept ones
	double median_ns = 0.0;              // L1 median inside the best batch
	double cv_pct = 0.0;
	bool stable = false;
	Status status = Status::Ok;
	uint32_t groups[3] = { 1, 1, 1 };
};

class Harness
{
public:
	bool init(const BenchConfig &cfg);
	bool load(const std::string &foz_path, const std::string &hashes_path);
	void run();
	void print_listing() const;
	void write_report(const std::string &out_path) const;
	bool any_ok() const;
	const std::string &error() const { return err; }

	~Harness();

private:
	friend class BenchCreator;

	bool create_device();
	bool create_arena();
	// One descriptor set per DISTINCT layout, not per pipeline: 15-19 layouts
	// cover 100,000+ pipelines, which is what makes this tractable at all.
	VkDescriptorSet dummy_set_for(Fossilize::Hash layout_hash);
	bool measure(PipelineEntry &e, Measurement &m);
	void compute_groups(const PipelineEntry &e, uint32_t out[3]) const;

	BenchConfig cfg;
	std::string err;

	VkInstance instance = VK_NULL_HANDLE;
	VkPhysicalDevice gpu = VK_NULL_HANDLE;
	VkDevice device = VK_NULL_HANDLE;
	VkQueue queue = VK_NULL_HANDLE;
	uint32_t queue_family = 0;
	double timestamp_period_ns = 1.0;
	std::string device_name, driver_info;

	VkCommandPool cmd_pool = VK_NULL_HANDLE;
	VkQueryPool query_pool = VK_NULL_HANDLE;
	std::vector<VkDescriptorPool> layout_pools;  // one per distinct set layout

	VkBuffer arena = VK_NULL_HANDLE;
	VkDeviceMemory arena_mem = VK_NULL_HANDLE;
	VkDeviceAddress arena_addr = 0;   // aimed at the MIDDLE of the allocation

	VkImage dummy_image = VK_NULL_HANDLE;
	VkDeviceMemory dummy_image_mem = VK_NULL_HANDLE;
	VkImageView dummy_view = VK_NULL_HANDLE;
	VkSampler dummy_sampler = VK_NULL_HANDLE;

	std::unordered_map<Fossilize::Hash, VkDescriptorSetLayout> set_layouts;
	std::unordered_map<Fossilize::Hash, std::vector<VkDescriptorSetLayoutBinding>> set_bindings;
	std::unordered_map<Fossilize::Hash, VkDescriptorSet> dummy_sets;
	std::unordered_map<VkPipelineLayout, std::vector<Fossilize::Hash>> layout_sets;
	std::unordered_map<Fossilize::Hash, uint32_t> module_local_size;  // by module hash

	std::vector<PipelineEntry> work;
	std::vector<Measurement> results;
	std::unordered_set<Fossilize::Hash> wanted;   // empty = take everything
	uint32_t created_failed = 0;
};
