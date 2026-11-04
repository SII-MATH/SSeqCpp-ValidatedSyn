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
    auto early = state.boundaries(object,d,3);
    require(contains(early,{1}) && !contains(early,{0}), "9000 is never an early boundary");
    node = Staircase{{{0},{1}},{{-1},{-1}},{9998,9998}};
    require(!state.d2(object,d), "unknown columns cannot be zero");
    require(state.cycle_upper(object,d).size() == 2, "unknown columns retain full upper space");
    AdamsDeg incoming_degree(10,133);
    auto& incoming=cat.GetNodesSS(object).front()[incoming_degree];
    auto original_incoming=incoming;
    require(state.dimension(object,incoming_degree)==3,"fixed actual incoming E2 degree");
    node=Staircase{{{0},{1}},{{1},{1,2}},{9997,9997}};
    incoming=Staircase{{{0},{1},{2}},{{2},{2},{-1}},{9998,9998,9997}};
    auto quotient_cycles=state.z4(object,d);
    require(quotient_cycles && quotient_cycles->size()==1 &&
            (*quotient_cycles)[0]==int1d({0,1}),"d3 kernel modulo the whole d2 image");
    node.diffs[1]=NULL_DIFF;
    require(!state.z4(object,d),"unknown d3 column must reject an exact Z4 computation");
    require(state.cycle_upper(object,d,4).size()==2,"unknown d3 keeps the larger cycle upper bound");
    incoming=original_incoming;
    bool outside = false;
    try { state.dimension(object,AdamsDeg(0,cat.GetTMax(object)+1)); }
    catch (const Missing&) { outside = true; }
    require(outside, "missing high-degree data is not vanishing");
    node = original;

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
