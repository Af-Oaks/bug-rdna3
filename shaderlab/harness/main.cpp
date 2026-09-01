// tcc-shaderbench -- execute real game shaders as a deterministic GPU workload.
//
// WHAT THIS IS FOR
// ----------------
// Metric 1 measures what the compiler *emitted* (registers, VOPD, occupancy).
// Metric 2 measures what the player sees (frames per second). Neither answers
// the question in between: does the emitted code actually cost less on the GPU?
//
// A .foz records enough to *create* a pipeline -- SPIR-V, descriptor set
// layouts, pipeline layouts -- but nothing about what the shader reads: no
// buffer contents, no descriptor bindings, no push constants, no dispatch
// sizes. This program supplies all of that synthetically, then dispatches the
// shader and times it with GPU timestamps.
//
// THE HONEST CAVEAT, WHICH TRAVELS WITH EVERY NUMBER THIS PRODUCES
// ----------------------------------------------------------------
// Synthetic inputs mean synthetic memory behaviour. Cache hit rates, texture
// residency and branch divergence will not match the real scene, so the
// absolute nanoseconds are NOT the game's nanoseconds. What is legitimate is
// the RELATIVE delta between two compilers on the same shader with identical
// synthetic inputs. Report it that way, always.
//
// THE DANGEROUS PART
// ------------------
// vkd3d-proton lowers D3D12 descriptor heaps into raw 64-bit GPU pointers read
// out of constant buffers -- one sampled Remnant II shader had 214 of them.
// There is no bounds checking on a physical pointer: a wrong one is a page
// fault, a lost queue, possibly a GPU reset that takes the desktop with it.
//
// Mitigation, and the reason this runs as its own process under a watchdog:
// allocate one large arena buffer, take its device address, aim at the MIDDLE
// so positive and negative offsets stay in range, and fill every uniform buffer
// with that address repeated every 8 bytes. Any 64-bit word the shader
// dereferences as a pointer then lands inside real memory.
//
// Bindless indexing gets the same treatment: robustness2 plus every descriptor
// array slot filled with the same valid dummy view, so any index resolves.

#include "harness.hpp"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace {

void usage()
{
	std::fprintf(stderr,
		"usage: tcc-shaderbench --foz <db.foz> [options]\n"
		"  --foz PATH            Fossilize database to benchmark (required)\n"
		"  --out PATH            run.json destination (default: stdout)\n"
		"  --hashes PATH         newline-separated pipeline hashes to include\n"
		"  --limit N             stop after N pipelines (0 = all, default 0)\n"
		"  --warmup N            warmup iterations, untimed        (default 50)\n"
		"  --iterations N        L1: dispatches per timed batch    (default 200)\n"
		"  --repetitions N       L2: timed batches per pipeline    (default 4)\n"
		"  --trim-worst N        L2: slowest batches discarded     (default 1)\n"
		"  --max-cv-pct F        stability gate on kept batches    (default 2.0)\n"
		"  --invocations N       fixed thread budget per shader    (default 1<<20)\n"
		"  --arena-mb N          dummy arena size in MiB           (default 256)\n"
		"  --list                create pipelines, print hashes, do not dispatch\n");
}

bool arg_u64(int &i, int argc, char **argv, uint64_t &out)
{
	if (i + 1 >= argc)
		return false;
	out = std::strtoull(argv[++i], nullptr, 10);
	return true;
}

} // namespace

int main(int argc, char **argv)
{
	BenchConfig cfg;
	std::string foz_path, out_path, hashes_path;
	bool list_only = false;

	for (int i = 1; i < argc; i++)
	{
		std::string a = argv[i];
		uint64_t v = 0;
		if (a == "--foz" && i + 1 < argc) foz_path = argv[++i];
		else if (a == "--out" && i + 1 < argc) out_path = argv[++i];
		else if (a == "--hashes" && i + 1 < argc) hashes_path = argv[++i];
		else if (a == "--limit" && arg_u64(i, argc, argv, v)) cfg.limit = v;
		else if (a == "--warmup" && arg_u64(i, argc, argv, v)) cfg.warmup_iterations = uint32_t(v);
		else if (a == "--iterations" && arg_u64(i, argc, argv, v)) cfg.iterations = uint32_t(v);
		else if (a == "--repetitions" && arg_u64(i, argc, argv, v)) cfg.repetitions = uint32_t(v);
		else if (a == "--trim-worst" && arg_u64(i, argc, argv, v)) cfg.trim_worst = uint32_t(v);
		else if (a == "--invocations" && arg_u64(i, argc, argv, v)) cfg.invocation_budget = v;
		else if (a == "--arena-mb" && arg_u64(i, argc, argv, v)) cfg.arena_bytes = v * 1024ull * 1024ull;
		else if (a == "--max-cv-pct" && i + 1 < argc) cfg.max_cv_pct = std::strtod(argv[++i], nullptr);
		else if (a == "--list") list_only = true;
		else if (a == "-h" || a == "--help") { usage(); return 0; }
		else { std::fprintf(stderr, "unknown argument: %s\n", a.c_str()); usage(); return 2; }
	}

	if (foz_path.empty())
	{
		usage();
		return 2;
	}
	if (cfg.repetitions <= cfg.trim_worst)
	{
		std::fprintf(stderr, "error: --repetitions (%u) must exceed --trim-worst (%u); "
		                     "trimming everything leaves nothing to average\n",
		             cfg.repetitions, cfg.trim_worst);
		return 2;
	}

	Harness harness;
	if (!harness.init(cfg))
	{
		std::fprintf(stderr, "error: %s\n", harness.error().c_str());
		return 3;
	}
	if (!harness.load(foz_path, hashes_path))
	{
		std::fprintf(stderr, "error: %s\n", harness.error().c_str());
		return 4;
	}

	if (list_only)
	{
		harness.print_listing();
		return 0;
	}

	harness.run();
	harness.write_report(out_path);
	// Exit code reflects whether ANY pipeline produced a usable number, not
	// whether all did: partial coverage is the expected case and is reported
	// as a coverage fraction, not hidden behind a failure.
	return harness.any_ok() ? 0 : 5;
}
