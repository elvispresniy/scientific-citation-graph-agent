// Weighted sampling without replacement. No graph, network or model calls.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_set>
#include <vector>
#ifdef _OPENMP
#include <omp.h>
#endif
#ifndef GTOPK_SOURCE_SHA256
#define GTOPK_SOURCE_SHA256 "unknown"
#endif

using Clock = std::chrono::steady_clock;
struct Row { uint64_t id; double weight; };
struct Item { uint64_t id; double score; };
struct Better {
    bool operator()(const Item& a, const Item& b) const {
        return a.score > b.score || (a.score == b.score && a.id < b.id);
    }
};

// Stateless per-ID pseudorandom keys: independent of partitioning and input order.
uint64_t mix64(uint64_t x) {
    x += UINT64_C(0x9e3779b97f4a7c15);
    x = (x ^ (x >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    x = (x ^ (x >> 27)) * UINT64_C(0x94d049bb133111eb);
    return x ^ (x >> 31);
}
double score(const Row& row, uint64_t seed) {
    const uint64_t bits = mix64(row.id ^ mix64(seed));
    // 52-bit midpoints: U is strictly inside (0,1), including after rounding.
    const double u = (static_cast<double>(bits >> 12) + 0.5) * 0x1p-52;
    return std::log(row.weight) - std::log(-std::log(u));
}
void keep(std::vector<Item>& heap, size_t k, Item item) {
    if (k == 0) return;
    if (heap.size() < k) {
        heap.push_back(item);
        std::push_heap(heap.begin(), heap.end(), Better{});
    } else if (Better{}(item, heap.front())) {
        std::pop_heap(heap.begin(), heap.end(), Better{});
        heap.back() = item;
        std::push_heap(heap.begin(), heap.end(), Better{});
    }
}
struct Result {
    std::vector<Item> selected;
    double local_seconds, merge_seconds, total_seconds;
    int threads;
};
Result sample(const std::vector<Row>& rows, size_t k, uint64_t seed, int threads) {
    const auto t0 = Clock::now();
    k = std::min(k, rows.size());
    std::vector<std::vector<Item>> local(static_cast<size_t>(threads));
    int actual = 1;
    auto work = [&](int tid, int team) {
        const size_t base = rows.size() / team, extra = rows.size() % team;
        const size_t begin = static_cast<size_t>(tid) * base + std::min<size_t>(tid, extra);
        const size_t end = begin + base + (static_cast<size_t>(tid) < extra);
        auto& heap = local[tid];
        heap.reserve(std::min(k, end - begin));
        for (size_t i = begin; i < end && k != 0; ++i)
            keep(heap, k, {rows[i].id, score(rows[i], seed)});
    };
    if (threads == 1) {
        work(0, 1);
    } else {
#ifdef _OPENMP
        omp_set_dynamic(0);
#pragma omp parallel num_threads(threads)
        {
#pragma omp single
            actual = omp_get_num_threads();
            work(omp_get_thread_num(), omp_get_num_threads());
        }
#else
        throw std::runtime_error("This binary has no OpenMP; use --threads 1 or rebuild");
#endif
    }
    const auto t1 = Clock::now();
    std::vector<Item> merged;
    merged.reserve(k);
    for (int tid = 0; tid < actual; ++tid)
        for (const auto& item : local[tid]) keep(merged, k, item);
    std::sort(merged.begin(), merged.end(), Better{});
    const auto t2 = Clock::now();
    return {std::move(merged), std::chrono::duration<double>(t1-t0).count(),
            std::chrono::duration<double>(t2-t1).count(),
            std::chrono::duration<double>(t2-t0).count(), actual};
}

uint64_t number(const std::string& s) {
    if (s.empty() || s.find_first_not_of("0123456789") != std::string::npos)
        throw std::runtime_error("Expected an unsigned integer: " + s);
    size_t used = 0;
    const auto n = std::stoull(s, &used);
    if (used != s.size()) throw std::runtime_error("Invalid integer: " + s);
    return n;
}
std::vector<Row> read_rows(const std::string& path) {
    std::ifstream file(path);
    if (!file) throw std::runtime_error("Cannot open input: " + path);
    std::vector<Row> rows;
    std::unordered_set<uint64_t> seen;
    std::string line;
    size_t lineno = 0;
    while (std::getline(file, line)) {
        ++lineno;
        std::istringstream stream(line);
        std::string id, weight, extra;
        if (!(stream >> id >> weight) || (stream >> extra))
            throw std::runtime_error("Expected ID<TAB>weight at line " + std::to_string(lineno));
        const uint64_t key = number(id);
        char* end = nullptr;
        const double w = std::strtod(weight.c_str(), &end);
        if (end != weight.c_str() + weight.size() || !std::isfinite(w) || w <= 0)
            throw std::runtime_error("Weight must be finite and positive at line " + std::to_string(lineno));
        if (!seen.insert(key).second) throw std::runtime_error("Duplicate ID at line " + std::to_string(lineno));
        rows.push_back({key, w});
    }
    if (!file.eof()) throw std::runtime_error("Input read failed");
    return rows;
}

int main(int argc, char** argv) {
    try {
        std::string input, pattern = "uniform";
        uint64_t n = 0, k = 20, seed = 42, threads = 1, repeat = 1, warmup = 0;
        bool synthetic = false;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--help") {
                std::cout << "(--input TSV | --synthetic N) [--k K] [--seed UINT64] "
                             "[--threads P] [--repeat R] [--warmup W] "
                             "[--weight-pattern uniform|skewed]\n";
                return 0;
            }
            if (++i >= argc) throw std::runtime_error("Missing value for " + arg);
            const std::string value = argv[i];
            if (arg == "--input") input = value;
            else if (arg == "--weight-pattern") pattern = value;
            else if (arg == "--synthetic") { n = number(value); synthetic = true; }
            else if (arg == "--k") k = number(value);
            else if (arg == "--seed") seed = number(value);
            else if (arg == "--threads") threads = number(value);
            else if (arg == "--repeat") repeat = number(value);
            else if (arg == "--warmup") warmup = number(value);
            else throw std::runtime_error("Unknown argument: " + arg);
        }
        if (synthetic == !input.empty()) throw std::runtime_error("Choose exactly one of --input and --synthetic");
        if (threads < 1 || threads > 1024 || repeat < 1 || repeat > 10000 || warmup > 10000)
            throw std::runtime_error("Invalid threads (1..1024), repeat (1..10000), or warmup (0..10000)");
        if (pattern != "uniform" && pattern != "skewed") throw std::runtime_error("Unknown weight pattern");
        if (n > std::numeric_limits<size_t>::max() / sizeof(Row) || k > std::numeric_limits<size_t>::max())
            throw std::runtime_error("Input size overflow");
        std::vector<Row> rows;
        if (synthetic) {
            rows.reserve(static_cast<size_t>(n));
            for (uint64_t i = 0; i < n; ++i)
                rows.push_back({i, pattern == "uniform" ? 1.0 : std::pow(10.0, static_cast<int>(i % 7) - 3)});
        } else rows = read_rows(input);
        for (uint64_t i = 0; i < warmup; ++i) sample(rows, static_cast<size_t>(k), seed, static_cast<int>(threads));
        std::vector<Result> runs;
        for (uint64_t i = 0; i < repeat; ++i) {
            auto result = sample(rows, static_cast<size_t>(k), seed, static_cast<int>(threads));
            if (!runs.empty()) {
                const auto& first = runs.front().selected;
                if (first.size() != result.selected.size()) throw std::runtime_error("Non-reproducible output");
                for (size_t j = 0; j < first.size(); ++j)
                    if (first[j].id != result.selected[j].id || first[j].score != result.selected[j].score)
                        throw std::runtime_error("Non-reproducible output");
            }
            runs.push_back(std::move(result));
        }
        std::cout << std::setprecision(17)
                  << "{\"algorithm_version\":\"gumbel-topk-splitmix64-v1\",\"source_sha256\":\""
                  << GTOPK_SOURCE_SHA256 << "\",\"compiler\":" << std::quoted(__VERSION__)
                  << ",\"openmp\":"
#ifdef _OPENMP
                  << _OPENMP
#else
                  << 0
#endif
                  << ",\"n\":" << rows.size() << ",\"k_requested\":" << k << ",\"seed\":" << seed
                  << ",\"threads_requested\":" << threads << ",\"threads_used\":" << runs.back().threads
                  << ",\"warmup\":" << warmup << ",\"timings\":[";
        for (size_t i = 0; i < runs.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << "{\"local_seconds\":" << runs[i].local_seconds
                      << ",\"merge_seconds\":" << runs[i].merge_seconds
                      << ",\"total_seconds\":" << runs[i].total_seconds << '}';
        }
        std::cout << "],\"selected\":[";
        const auto& selected = runs.back().selected;
        for (size_t i = 0; i < selected.size(); ++i) {
            if (i) std::cout << ',';
            std::cout << "{\"id\":" << selected[i].id << ",\"score\":" << selected[i].score << '}';
        }
        std::cout << "]}\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "gumbel_topk: " << e.what() << '\n';
        return 1;
    }
}
