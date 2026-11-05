// Direct tests of the finite-space predicates and disabled native producers.
#include "../../ss/validated_syn.cpp"
#include <iostream>
#include <stdexcept>

static void require(bool b, const char* message) {
    if (!b) throw std::runtime_error(message);
}
int main(int argc, char** argv) {
    using namespace validated_syn;
    require(argc == 2, "fixture directory required");
    auto k = kernel({{0},{0}});
    require(k.size() == 1 && k[0] == int1d({0,1}), "whole kernel, including combinations");
    require(!contained(k, {{0}}), "a missed terminal kernel direction must reject");
    require(contained(k, {{0,1}}), "a genuine sufficient boundary accepts");
    require(!solve({{0}}, {1}), "inconsistent affine relation must reject");
    auto relation = solve({{0,1},{1}}, {0});
    require(relation && linear_apply({{0,1},{1}}, *relation) == int1d({0}), "affine witness");

    Category cat(argv[1], "", SSFlag::cofseq | SSFlag::no_save, false, false);
    State state{cat};
    auto object = cat.GetIndexCwByName("S0");
    AdamsDeg d(9,132);
    auto& node = cat.GetNodesSS(object).front()[d];
    auto original = node;
    require(state.dimension(object,d) == 2, "fixed actual E2 test degree");
    node = Staircase{{{0},{1}},{{},{}},{9000,2}};
    auto early = State{cat}.boundaries(object,d,3);
    require(contains(early,{1}) && !contains(early,{0}), "9000 is never an early boundary");
    node = Staircase{{{0},{1}},{{-1},{-1}},{9998,9998}};
    require(!State{cat}.d2(object,d), "unknown columns cannot be zero");
    require(State{cat}.cycle_upper(object,d).size() == 2, "unknown columns retain full upper space");
    AdamsDeg incoming_degree(10,133);
    auto& incoming=cat.GetNodesSS(object).front()[incoming_degree];
    auto original_incoming=incoming;
    require(state.dimension(object,incoming_degree)==3,"fixed actual incoming E2 degree");
    node=Staircase{{{0},{1}},{{1},{1,2}},{9997,9997}};
    incoming=Staircase{{{0},{1},{2}},{{2},{2},{-1}},{9998,9998,9997}};
    auto quotient_cycles=State{cat}.z4(object,d);
    require(quotient_cycles && quotient_cycles->size()==1 &&
            (*quotient_cycles)[0]==int1d({0,1}),"d3 kernel modulo the whole d2 image");
    node.diffs[1]=NULL_DIFF;
    require(!State{cat}.z4(object,d),"unknown d3 column must reject an exact Z4 computation");
    require(State{cat}.cycle_upper(object,d,4).size()==2,"unknown d3 keeps the larger cycle upper bound");
    incoming=original_incoming;
    bool outside = false;
    try { state.dimension(object,AdamsDeg(0,cat.GetTMax(object)+1)); }
    catch (const Missing&) { outside = true; }
    require(outside, "missing high-degree data is not vanishing");
    node = original;

    // Reuse is explicit and bounded to a read-only State frame.
    auto& cache=cat.GetValidatedSynCache();
    auto old_hits=cache.memo_hits,old_rank_hits=cache.rank_hits;
    {
        State frame{cat};
        auto first=frame.d2(object,d);
        for (int i=0;i<20;++i) require(frame.d2(object,d)==first,"cached d2 equivalence");
        (void)frame.staircase(object,d); (void)frame.staircase(object,d);
    }
    require(cache.memo_hits>old_hits && cache.rank_hits>old_rank_hits,"actual cache hits required");
    // Fixed map columns agree with direct native evaluation on basis vectors
    // and nontrivial sums, and can be reused across State frames.
    const std::vector<AdamsDeg> degrees={{1,1},{7,131},{8,132},{9,132},{10,133},{12,134}};
    size_t map_tests=0;
    for (size_t ordinal=0;ordinal<cat.GetMaps().size();++ordinal) {
        auto& f=cat.GetMaps()[ordinal];
        for (auto degree:degrees) {
            State frame{cat};
            int n=frame.dimension(f->from,degree);
            if (!n || degree.t>f->t_max) continue;
            if ((degree+f->deg).s<0 || (degree+f->deg).stem()<0) continue;
            (void)frame.dimension(f->to,degree+f->deg);
            int1d vector;
            for (int i=0;i<std::min(n,8);++i) vector.push_back(i);
            auto direct=f->map(vector,degree,cat);
            require(frame.map(ordinal,degree,vector)==direct,"cached linear map must equal native map");
            require(State{cat}.map(ordinal,degree,vector)==direct,"fixed map cache across frames");
            ++map_tests;
        }
    }
    require(map_tests>=10 && cache.map_hits>0,"nontrivial fixed map tests and reuse");
    // A trial changes the state. Its computed spaces must disappear on PopNode.
    const auto trial_flags=SSFlag::cofseq|SSFlag::no_save;
    auto before=State{cat}.d2(object,d);
    cat.AddNode(trial_flags);
    auto& trial=cat.GetNodesSS(object).back()[d];
    trial=Staircase{{{0},{1}},{{},{}},{9000,9000}};
    auto inside=State{cat}.d2(object,d);
    require(inside && (!before || *inside!=*before),"trial result must reflect its own state");
    cat.PopNode(trial_flags);
    require(State{cat}.d2(object,d)==before,"rollback cannot reuse trial knowledge");
    // A new accepted state also needs a new frame; unknown columns stay unknown.
    node=Staircase{{{0},{1}},{{},{}},{9000,9000}};
    require(State{cat}.d2(object,d).has_value(),"known state is known");
    node=Staircase{{{0},{1}},{{-1},{-1}},{9998,9998}};
    require(!State{cat}.d2(object,d),"new state must not reuse cached known columns");
    node=original;

    // Identical representative workload in enabled and disabled modes. It
    // measures these checks only, not the full SS search or a speedup promise.
    auto workload=[&](bool enabled) {
        cache.enabled=enabled;
        auto start=std::chrono::steady_clock::now();
        size_t total=0;
        for (int repetition=0;repetition<150;++repetition) {
            State frame{cat};
            for (int k=2;k<=12;++k) {
                total+=frame.boundaries(object,d,k).size();
                total+=frame.cycle_upper(object,d,4).size();
                auto matrix=frame.d2(object,d);
                total+=matrix ? matrix->size() : 0;
                total+=frame.staircase(object,d).basis.size();
            }
        }
        return std::pair{total,std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()};
    };
    auto uncached=workload(false),cached=workload(true);
    require(uncached.first==cached.first,"cached/reference workload outputs differ");
    std::cout<<"CACHE_BENCH uncached_seconds="<<uncached.second<<" cached_seconds="<<cached.second
             <<" map_tests="<<map_tests<<" memo_hits="<<cache.memo_hits<<'\n';

    bool disabled = false;
    AdamsDeg output;
    int1d image;
    try { (void)cat.GetSynImage(IndexCof(size_t(0),size_t(0)),d,{0},9998,output,image,-1,0); }
    catch (const std::exception&) { disabled = true; }
    require(disabled, "legacy getter must fail closed");
    auto no_cofiber_syn = cat.DeduceDiffBySyntheticCofseq(SSFlag::synthetic);
    require(!no_cofiber_syn && !no_cofiber_syn.IsChanged(), "cofiber synthetic producers disabled");
    std::cout << "PASS: full kernel, affine relation, strict boundaries, unknown/range handling, legacy and cofiber barriers\n";
}
