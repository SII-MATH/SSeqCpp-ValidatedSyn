#include "validated_syn.h"
#include <map>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <tuple>
#include <optional>
#include <stdexcept>

namespace validated_syn {
struct Cache {
    using MapKey=std::tuple<size_t,int,int,int>;
    bool enabled=!(std::getenv("SS_VALIDATED_CACHE") && std::string(std::getenv("SS_VALIDATED_CACHE"))=="off");
    std::map<MapKey,int1d> map_columns;
    uint64_t map_hits=0,map_evaluations=0,memo_hits=0,memo_evaluations=0,
             rank_hits=0,rank_evaluations=0,evictions=0,frames=0;
    double rule_seconds=0;
    ~Cache() {
        if (std::getenv("SS_VALIDATED_CACHE_STATS"))
            std::cerr << "VALIDATED_CACHE " << json({{"enabled",enabled},{"map_hits",map_hits},
                {"map_evaluations",map_evaluations},{"memo_hits",memo_hits},
                {"memo_evaluations",memo_evaluations},{"rank_hits",rank_hits},
                {"rank_evaluations",rank_evaluations},{"map_cache_entries",map_columns.size()},
                {"evictions",evictions},{"frames",frames},{"rule_seconds",rule_seconds}}).dump() << '\n';
    }
};
}
validated_syn::Cache& Category::GetValidatedSynCache() const {
    if (!validated_syn_cache_) validated_syn_cache_=std::make_shared<validated_syn::Cache>();
    return *validated_syn_cache_;
}
namespace validated_syn {
namespace {
using Space = int2d;
struct Missing : std::runtime_error { using std::runtime_error::runtime_error; };

int1d linear_apply(const Space& columns, const int1d& v) {
    int1d result;
    for (int i : v) {
        if (i < 0 || size_t(i) >= columns.size()) throw Missing("invalid column");
        result = lina::add(result, columns[i]);
    }
    return result;
}
Space identity(size_t n) {
    Space result;
    for (size_t i = 0; i < n; ++i) result.push_back({int(i)});
    return result;
}
Space kernel(const Space& columns) {
    Space image, ker, inverse;
    lina::SetLinearMap(columns, image, ker, inverse);
    return ker;
}
Space intersection(const Space& left, const Space& right) {
    Space columns=left, result;
    columns.insert(columns.end(),right.begin(),right.end());
    for (auto& relation:kernel(columns)) {
        int1d v;
        for (int i:relation) if (size_t(i)<left.size()) v=lina::add(v,left[i]);
        result.push_back(std::move(v));
    }
    return lina::GetSpace(result);
}
bool contains(const Space& space, const int1d& v) {
    return lina::Residue(lina::GetSpace(space), v).empty();
}
bool contained(const Space& left, const Space& right) {
    auto basis = lina::GetSpace(right);
    for (auto& v : left) if (!lina::Residue(basis, v).empty()) return false;
    return true;
}
std::optional<int1d> solve(const Space& columns, const int1d& target) {
    Space image, ker, inverse;
    lina::SetLinearMap(columns, image, ker, inverse);
    if (!lina::Residue(image, target).empty()) return std::nullopt;
    return lina::GetImage(image, inverse, target);
}
int1d pair(const int1d& a, const int1d& b) {
    int1d result;
    for (int i : a) result.push_back(2 * i);
    for (int i : b) result.push_back(2 * i + 1);
    std::sort(result.begin(), result.end());
    return result;
}
int1d triple(const int1d& a, const int1d& b, const int1d& c) {
    int1d result;
    for (int i : a) result.push_back(3*i);
    for (int i : b) result.push_back(3*i+1);
    for (int i : c) result.push_back(3*i+2);
    std::sort(result.begin(),result.end());
    return result;
}

struct State {
    using Key=std::tuple<uint32_t,size_t,int,int,int>;
    struct Graph { Space domain, images; };
    Category& cat;
    Cache& cache;
    std::chrono::steady_clock::time_point started=std::chrono::steady_clock::now();
    mutable std::set<Key> checked_staircases;
    mutable std::map<Key,std::optional<Space>> d2_memo,z4_memo;
    mutable std::map<Key,Space> boundary_memo,upper_memo,lower_memo,permanent_memo,boundary_upper_memo;
    mutable std::map<Key,bool> e3_memo;
    mutable std::map<Key,Graph> graph_memo;
    explicit State(Category& value):cat(value),cache(value.GetValidatedSynCache()) {++cache.frames;}
    ~State() {cache.rule_seconds+=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();}
    static Key key(IndexUniv object,AdamsDeg d,int parameter=0) {
        return {object.type,object.index,d.s,d.t,parameter};
    }
    template<class T,class Compute> T memo(std::map<Key,T>& table,Key k,Compute compute) const {
        if (cache.enabled) {
            auto found=table.find(k);
            if (found!=table.end()) {++cache.memo_hits;return found->second;}
        }
        ++cache.memo_evaluations;
        auto result=compute();
        if (cache.enabled) table.emplace(k,result);
        return result;
    }
    int dimension(IndexUniv object, AdamsDeg d) const {
        if (d.s < 0 || d.t < d.s) return 0;
        if (d.t > cat.GetTMax(object)) throw Missing("outside E2 range");
        if (object.isRing()) {
            const auto& b = cat.GetRings()[object.index].basis;
            return b.has(d) ? int(b.at(d).size()) : 0;
        }
        const auto& b = cat.GetModules()[object.index].basis;
        return b.has(d) ? int(b.at(d).size()) : 0;
    }
    const Staircase& staircase(IndexUniv object, AdamsDeg d) const {
        int n = dimension(object, d);
        if (!n) return EmptyStaircase;
        const auto& ss = cat.GetNodesSS(object);
        if (!ss.front().has(d)) throw Missing("missing nonempty staircase");
        const auto& sc = ss.GetRecentSc(d);
        if (sc.basis.size()!=size_t(n)) throw Missing("incomplete staircase");
        auto k=key(object,d);
        if (cache.enabled && checked_staircases.count(k)) ++cache.rank_hits;
        else {
            ++cache.rank_evaluations;
            if (lina::GetSpace(sc.basis).size()!=size_t(n)) throw Missing("incomplete staircase");
            if (cache.enabled) checked_staircases.insert(k);
        }
        return sc;
    }
    int1d map(size_t ordinal, AdamsDeg d, const int1d& v) const {
        auto& f = cat.GetMaps()[ordinal];
        int source_size=dimension(f->from,d);
        dimension(f->to,d+f->deg);
        if (d.t>f->t_max) throw Missing("outside map range");
        if (v.empty()) return {};
        if (v.front()<0 || v.back()>=source_size) throw Missing("invalid map source coordinate");
        if (!cache.enabled) {++cache.map_evaluations;return f->map(v,d,cat);}
        int1d result;
        for (int i:v) {
            Cache::MapKey k{ordinal,d.s,d.t,i};
            auto found=cache.map_columns.find(k);
            if (found==cache.map_columns.end()) {
                // Fixed E2 maps are linear and unchanged by trials/rollback.
                // Bound retained columns without discarding any SS knowledge.
                if (cache.map_columns.size()>=65536) {cache.map_columns.clear();++cache.evictions;}
                auto column=f->map({i},d,cat);
                ++cache.map_evaluations;
                found=cache.map_columns.emplace(k,std::move(column)).first;
            } else ++cache.map_hits;
            result=lina::add(result,found->second);
        }
        return result;
    }
    Space map_space(size_t ordinal, AdamsDeg d, const Space& p) const {
        Space result;
        for (auto& v : p) result.push_back(map(ordinal, d, v));
        return result;
    }
    Space boundaries(IndexUniv object, AdamsDeg d, int before) const {
        return memo(boundary_memo,key(object,d,before),[&]{return boundaries_uncached(object,d,before);});
    }
    Space boundaries_uncached(IndexUniv object, AdamsDeg d, int before) const {
        const auto& sc = staircase(object, d);
        Space result;
        for (size_t i = 0; i < sc.basis.size(); ++i)
            if (sc.levels[i] < std::min(before, LEVEL_PERM)) result.push_back(sc.basis[i]);
        return lina::GetSpace(result);
    }
    // Full E2 d2 matrix, only when every column is actually known.
    std::optional<Space> d2(IndexUniv object, AdamsDeg d) const {
        return memo(d2_memo,key(object,d),[&]{return d2_uncached(object,d);});
    }
    std::optional<Space> d2_uncached(IndexUniv object, AdamsDeg d) const {
        const auto& sc = staircase(object, d);
        Space values;
        for (size_t i = 0; i < sc.basis.size(); ++i) {
            if (sc.levels[i] >= LEVEL_MAX - 2 && sc.diffs[i] == NULL_DIFF)
                return std::nullopt;
            if (sc.levels[i] > LEVEL_MAX - 2) return std::nullopt;
            values.push_back(sc.levels[i] == LEVEL_MAX - 2 ? sc.diffs[i] : int1d{});
        }
        Space result;
        Space basis_image,basis_kernel,basis_inverse;
        lina::SetLinearMap(sc.basis,basis_image,basis_kernel,basis_inverse);
        for (auto& e : identity(sc.basis.size())) {
            if (!lina::Residue(basis_image,e).empty()) throw Missing("noninvertible E2 basis");
            auto coefficients=lina::GetImage(basis_image,basis_inverse,e);
            result.push_back(linear_apply(values,coefficients));
        }
        return result;
    }
    std::optional<Space> z4(IndexUniv object, AdamsDeg d) const {
        return memo(z4_memo,key(object,d),[&]{return z4_uncached(object,d);});
    }
    std::optional<Space> z4_uncached(IndexUniv object, AdamsDeg d) const {
        auto out=d2(object,d), incoming=d2(object,d+AdamsDeg(1,1));
        if (!out || !incoming) return std::nullopt;
        auto cycles=kernel(*out);
        const auto& sc=staircase(object,d);
        Space images;
        Space basis_image,basis_kernel,basis_inverse;
        lina::SetLinearMap(sc.basis,basis_image,basis_kernel,basis_inverse);
        for (auto& cycle:cycles) {
            if (!lina::Residue(basis_image,cycle).empty()) throw Missing("cycle outside complete E2 basis");
            auto coefficients=lina::GetImage(basis_image,basis_inverse,cycle);
            int1d image;
            for (int i:coefficients) {
                if (sc.levels[i]>=LEVEL_MAX-2 ||
                    (sc.levels[i]==LEVEL_MAX-3 && sc.diffs[i]==NULL_DIFF)) return std::nullopt;
                if (sc.levels[i]==LEVEL_MAX-3) image=lina::add(image,sc.diffs[i]);
            }
            images.push_back(std::move(image));
        }
        auto count=images.size();
        images.insert(images.end(),incoming->begin(),incoming->end());
        Space result;
        for (auto& relation:kernel(images)) {
            int1d cycle;
            for (int i:relation) if (size_t(i)<count) cycle=lina::add(cycle,cycles[i]);
            result.push_back(std::move(cycle));
        }
        return lina::GetSpace(result);
    }
    // Upper bounds only use complete matrices; unknown columns enlarge them.
    Space cycle_upper(IndexUniv object, AdamsDeg d, int page=3) const {
        return memo(upper_memo,key(object,d,page),[&]{return cycle_upper_uncached(object,d,page);});
    }
    Space cycle_upper_uncached(IndexUniv object, AdamsDeg d, int page) const {
        if (page>=4) {
            auto cycles=z4(object,d);
            if (cycles) return *cycles;
        }
        auto matrix = d2(object, d);
        return matrix ? kernel(*matrix) : identity(dimension(object, d));
    }
    bool e3_zero(IndexUniv object, AdamsDeg d) const {
        return memo(e3_memo,key(object,d),[&]{return e3_zero_uncached(object,d);});
    }
    bool e3_zero_uncached(IndexUniv object, AdamsDeg d) const {
        if (!dimension(object, d)) return true;
        auto out = d2(object, d), in = d2(object, d - AdamsDeg(2, 1));
        if (!out || !in) return false;
        return contained(kernel(*out), *in);
    }
    Space cycle_lower(IndexUniv object, AdamsDeg d, int page) const {
        return memo(lower_memo,key(object,d,page),[&]{return cycle_lower_uncached(object,d,page);});
    }
    Space cycle_lower_uncached(IndexUniv object, AdamsDeg d, int page) const {
        const auto& sc = staircase(object, d);
        Space result;
        for (size_t i = 0; i < sc.basis.size(); ++i)
            if (sc.levels[i] <= LEVEL_MAX - page) result.push_back(sc.basis[i]);
        bool vanishing = true;
        for (int q = 3; q < page; ++q)
            if (!e3_zero(object, d + AdamsDeg(q, q - 1))) { vanishing = false; break; }
        if (vanishing) {
            auto matrix = d2(object, d);
            if (matrix) {
                auto cycles = kernel(*matrix);
                result.insert(result.end(), cycles.begin(), cycles.end());
            }
        }
        if (page>=4) {
            bool later_zero=true;
            for (int q=4;q<page;++q)
                if (!e3_zero(object,d+AdamsDeg(q,q-1))) {later_zero=false;break;}
            if (later_zero) {
                auto cycles=z4(object,d);
                if (cycles) result.insert(result.end(),cycles->begin(),cycles->end());
            }
        }
        return lina::GetSpace(result);
    }
    // P is an upper bound on permanent representatives. The native fixed-prefix
    // criterion also checks that removed outgoing targets cannot be earlier
    // boundaries; an outgoing row alone is not sufficient to remove a direction.
    Space permanent_upper(IndexUniv object, AdamsDeg d) const {
        return memo(permanent_memo,key(object,d),[&]{return permanent_upper_uncached(object,d);});
    }
    Space permanent_upper_uncached(IndexUniv object, AdamsDeg d) const {
        const auto& sc = staircase(object, d);
        if (sc.basis.empty()) return {};
        const auto& nodes = cat.GetNodesSS(object);
        size_t end = sc.basis.size();
        for (size_t i = sc.basis.size(); i-- > 0;) {
            if (sc.diffs[i] == NULL_DIFF || sc.levels[i] <= LEVEL_PERM) break;
            if (i == 0 || sc.levels[i] != sc.levels[i - 1]) {
                int page = LEVEL_MAX - sc.levels[i];
                auto target = d + AdamsDeg(page, page - 1);
                // Missing high-degree input never means that no earlier
                // incoming differential exists.
                if (target.t > cat.GetTMax(object) || IsPossTgt(nodes, target, page - 1)) break;
                end = i;
            }
        }
        Space prefix(sc.basis.begin(), sc.basis.begin() + end);
        auto upper = cycle_upper(object, d,4);
        return intersection(prefix,upper);
    }
    Graph differential(IndexUniv object, AdamsDeg d, int page) const {
        return memo(graph_memo,key(object,d,page),[&]{return differential_uncached(object,d,page);});
    }
    Graph differential_uncached(IndexUniv object, AdamsDeg d, int page) const {
        const auto& sc = staircase(object, d);
        Graph graph;
        for (size_t i = 0; i < sc.basis.size(); ++i) {
            int level = sc.levels[i];
            if (level > LEVEL_MAX - page) continue;
            if (level == LEVEL_MAX - page && sc.diffs[i] == NULL_DIFF) continue;
            graph.domain.push_back(sc.basis[i]);
            graph.images.push_back(level == LEVEL_MAX - page ? sc.diffs[i] : int1d{});
        }
        return graph;
    }
    Space boundary_upper(IndexUniv object, AdamsDeg d, int before) const {
        return memo(boundary_upper_memo,key(object,d,before),[&]{return boundary_upper_uncached(object,d,before);});
    }
    Space boundary_upper_uncached(IndexUniv object, AdamsDeg d, int before) const {
        int n=dimension(object,d);
        if (!n) return {};
        auto result=boundaries(object,d,before);
        for (int page=2;page<before;++page) {
            auto source=d-AdamsDeg(page,page-1);
            if (source.s<0 || source.stem()<0) continue;
            auto upper=page==2 ? identity(dimension(object,source)) : cycle_upper(object,source,page);
            auto graph=differential(object,source,page);
            Space domain_image,domain_kernel,domain_inverse;
            lina::SetLinearMap(graph.domain,domain_image,domain_kernel,domain_inverse);
            // Without full source coverage the only safe target bound is E2.
            for (auto& v:upper) {
                if (!lina::Residue(domain_image,v).empty()) return identity(n);
                auto coefficients=lina::GetImage(domain_image,domain_inverse,v);
                result.push_back(linear_apply(graph.images,coefficients));
            }
        }
        return lina::GetSpace(result);
    }
};

struct Lift { int1d z, v; };
std::optional<Lift> find_lift(const State& st, size_t h, size_t g,
        IndexUniv z_object, AdamsDeg z_degree, const int1d& head, int k,
        const Space& candidates, AdamsDeg candidate_degree,
        const Space& source_errors = {}) {
    auto graph = st.differential(z_object, z_degree, k);
    auto hz = st.map_space(h, z_degree, graph.domain);
    auto gp = st.map_space(g, candidate_degree, candidates);
    Space equations;
    for (size_t i = 0; i < graph.domain.size(); ++i)
        equations.push_back(pair(hz[i], graph.images[i]));
    for (auto& v : gp) equations.push_back(pair({}, v));
    auto bz = st.boundaries(z_object, z_degree + AdamsDeg(k, k - 1), k);
    for (auto& v : bz) equations.push_back(pair({}, v));
    for (auto& v : source_errors) equations.push_back(pair(v, {}));
    auto coefficients = solve(equations, pair(head, {}));
    if (!coefficients) return std::nullopt;
    Lift result;
    for (int i : *coefficients) {
        if (size_t(i) < graph.domain.size()) result.z = lina::add(result.z, graph.domain[i]);
        else if (size_t(i) < graph.domain.size() + candidates.size())
            result.v = lina::add(result.v, candidates[i - graph.domain.size()]);
    }
    return result;
}

struct EarlyLift { int1d c, z, v; };
std::optional<EarlyLift> early_lift(const State& st, size_t g,
        IndexUniv y_object, AdamsDeg c_degree, const int1d& head,
        IndexUniv z_object, AdamsDeg z_degree, int length,
        const Space& candidates, AdamsDeg v_degree) {
    auto early = st.differential(y_object,c_degree,2);
    auto graph = st.differential(z_object,z_degree,length);
    auto gc = st.map_space(g,c_degree,early.domain);
    auto gv = st.map_space(g,v_degree,candidates);
    auto b = st.boundaries(z_object,z_degree + AdamsDeg(length,length-1),length);
    Space columns;
    for (size_t i=0;i<early.domain.size();++i)
        columns.push_back(triple(early.images[i],gc[i],{}));
    for (size_t i=0;i<graph.domain.size();++i)
        columns.push_back(triple({},graph.domain[i],graph.images[i]));
    for (auto& v:gv) columns.push_back(triple({},{},v));
    for (auto& v:b) columns.push_back(triple({},{},v));
    auto solution = solve(columns,triple(head,{},{}));
    if (!solution) return std::nullopt;
    EarlyLift result;
    for (int i:*solution) {
        if (size_t(i)<early.domain.size()) result.c=lina::add(result.c,early.domain[i]);
        else if (size_t(i)<early.domain.size()+graph.domain.size())
            result.z=lina::add(result.z,graph.domain[i-early.domain.size()]);
        else if (size_t(i)<early.domain.size()+graph.domain.size()+candidates.size())
            result.v=lina::add(result.v,candidates[i-early.domain.size()-graph.domain.size()]);
    }
    return result;
}

bool middle(const State& st, IndexUniv x, IndexUniv z, AdamsDeg target,
            size_t h, int k, bool selective, size_t f, IndexUniv y, int known_base=0) {
    for (int j = 1; j <= k - 2; ++j) {
        int m = k - j;
        auto d = target + AdamsDeg(j, j);
        auto dz = d - st.cat.GetMaps()[h]->deg;
        auto upper = st.cycle_upper(x, d,m+1);
        auto rhs = st.boundaries(x, d, j + 2);
        auto images = st.map_space(h, dz, st.cycle_lower(z, dz, m + 1));
        rhs.insert(rhs.end(), images.begin(), images.end());
        if (selective) {
            auto mapped = st.map_space(f, d, upper);
            auto p = st.permanent_upper(y, d + st.cat.GetMaps()[f]->deg);
            if (known_base) p=intersection(p,st.boundary_upper(y,
                d+st.cat.GetMaps()[f]->deg,known_base+j));
            mapped.insert(mapped.end(), p.begin(), p.end());
            Space relevant;
            for (auto& relation : kernel(mapped)) {
                int1d value;
                for (int i : relation) if (size_t(i) < upper.size()) value = lina::add(value, upper[i]);
                relevant.push_back(std::move(value));
            }
            upper = std::move(relevant);
        }
        if (!contained(upper, rhs)) return false;
    }
    return true;
}
} // namespace

std::vector<Conclusion> finite_zigzags(Category& cat, IndexUniv object, AdamsDeg d,
                                     const int1d& x, const int1d& u, int r) {
    std::vector<Conclusion> result;
    if (x.empty() || u.empty() || r < 2 || r >= R_PERM) return result;
    State st{cat};
    const auto target = d + AdamsDeg(r, r - 1);
    // All witnesses are read from the current state before any new conclusion
    // is written. No recursive call to GetSynImage occurs here.
    for (auto index : cat.GetIndexCofs(object)) {
        try {
            auto& triangle = cat.GetCofSeqs()[index.index];
            size_t a = index.iTri, b = NextiTri(a), c = PreviTri(a);
            size_t f = triangle.indexMap[a], g = triangle.indexMap[b], h = triangle.indexMap[c];
            auto& fm = cat.GetMaps()[f]; auto& gm = cat.GetMaps()[g]; auto& hm = cat.GetMaps()[h];
            if (fm->deg.s < 0 || gm->deg.s < 0 || hm->deg.s < 0 ||
                fm->deg.s + gm->deg.s + hm->deg.s != 1 ||
                fm->deg.t + gm->deg.t + hm->deg.t != 0) continue;
            auto y_object = triangle.indexCw[b], z_object = triangle.indexCw[c];
            auto y_degree = d + fm->deg;
            auto y = st.map(f, d, x);
            auto fu = st.map(f, target, u);
            // The source and target early-d2 corrections are independent
            // propositions, with their own whole H-image conditions.
            for (int length=3;length<=12;++length) {
                try {
                    if (r >= length) {
                        int page=r-length+2;
                        auto hy=st.map_space(h,d-hm->deg,identity(st.dimension(z_object,d-hm->deg)));
                        auto yd=d+fm->deg+AdamsDeg(length-2,length-2);
                        auto corr_degree=d+AdamsDeg(length-2,length-2);
                        auto corr=st.map_space(f,corr_degree,identity(st.dimension(object,corr_degree)));
                        if (page>=2 && contained(hy,st.boundaries(object,d,3)) &&
                            middle(st,object,z_object,d,h,length-1,false,f,y_object) &&
                            contained(corr,st.cycle_lower(y_object,yd,page+1))) {
                            auto cd=d+fm->deg-AdamsDeg(2,1);
                            auto lift=early_lift(st,g,y_object,cd,y,z_object,cd+gm->deg,length,
                                                 identity(st.dimension(y_object,yd)),yd);
                            if (lift && cat.IsNewDiff(cat.GetNodesSS(y_object),yd,lift->v,fu,page)) {
                                json witness={{"rule","source-early-d2"},{"triangle",triangle.name},
                                    {"slot",a},{"r",r},{"L",length},{"D",page},
                                    {"x",x},{"u",u},{"c",lift->c},{"z",lift->z},{"y",lift->v},{"v",fu},
                                    {"whole_H_image_checked",true},{"whole_middle_checked",true},
                                    {"whole_correction_image_checked",true}};
                                result.push_back({y_object,yd,page,lift->v,fu,witness.dump()});
                            }
                        }
                    }
                    if (r>=3 && !y.empty() && contains(st.cycle_lower(y_object,y_degree,r),y)) {
                        int page=r+length-2;
                        if (page>=R_PERM) continue;
                        auto hz=st.map_space(h,target-hm->deg,
                                           identity(st.dimension(z_object,target-hm->deg)));
                        if (!contained(hz,st.boundaries(object,target,3))) continue;
                        if (!middle(st,object,z_object,target,h,length-1,true,f,y_object)) continue;
                        auto vd=y_degree+AdamsDeg(page,page-1);
                        auto p=st.permanent_upper(y_object,vd);
                        auto gp=st.map_space(g,vd,p);
                        Space terminal;
                        for (auto& relation:kernel(gp)) terminal.push_back(linear_apply(p,relation));
                        if (!contained(terminal,st.boundaries(y_object,vd,page))) continue;
                        auto cd=target+fm->deg-AdamsDeg(2,1);
                        auto lift=early_lift(st,g,y_object,cd,fu,z_object,cd+gm->deg,length,p,vd);
                        if (lift && cat.IsNewDiff(cat.GetNodesSS(y_object),y_degree,y,lift->v,page)) {
                            json witness={{"rule","target-early-d2"},{"triangle",triangle.name},
                                {"slot",a},{"r",r},{"L",length},{"D",page},
                                {"x",x},{"u",u},{"c",lift->c},{"z",lift->z},{"y",y},{"v",lift->v},
                                {"whole_H_image_checked",true},{"whole_middle_checked",true},
                                {"whole_terminal_kernel_checked",true}};
                            result.push_back({y_object,y_degree,page,y,lift->v,witness.dump()});
                        }
                    }
                } catch (const Missing&) { }
            }
            if (y.empty()) {
                // Proposition source-finite-differential. Both finite lifts
                // are solved from current differential graphs. The complete
                // correction image is checked independently of the chosen y.
                for (int k1 = 2; k1 < r && k1 <= 12; ++k1) {
                    auto yd = d + fm->deg + AdamsDeg(k1 - 1, k1 - 1);
                    if (!middle(st, object, z_object, d, h, k1, false, f, y_object)) continue;
                    auto top = find_lift(st,h,g,z_object,d - hm->deg,x,k1,
                                         identity(st.dimension(y_object,yd)),yd);
                    if (!top) continue;
                    auto correction_degree = d + AdamsDeg(k1 - 1,k1 - 1);
                    auto corrections = st.map_space(f,correction_degree,
                        identity(st.dimension(object,correction_degree)));
                    for (int k2 = 1; k2 <= 12; ++k2) {
                        try {
                            int page = r + k2 - k1;
                            if (page < 2 || page >= R_PERM) continue;
                            if (!contained(corrections,st.cycle_lower(y_object,yd,page+1))) continue;
                            int1d v = fu, z;
                            bool known_survival=false;
                            if (k2 >= 2) {
                                auto zd = target - hm->deg;
                                auto vd = zd + AdamsDeg(k2,k2-1) - gm->deg;
                                auto p = st.permanent_upper(y_object,vd);
                                auto gp = st.map_space(g,vd,p);
                                Space terminal;
                                for (auto& rel : kernel(gp)) terminal.push_back(linear_apply(p,rel));
                                if (!contained(terminal,st.boundaries(y_object,vd,page))) continue;
                                if (!middle(st,object,z_object,target,h,k2,true,f,y_object)) {
                                    if (!contains(st.cycle_lower(y_object,yd,page),top->v) ||
                                        !middle(st,object,z_object,target,h,k2,true,f,y_object,r-k1+1)) continue;
                                    known_survival=true;
                                }
                                auto bottom = find_lift(st,h,g,z_object,zd,u,k2,p,vd);
                                if (!bottom) continue;
                                z = bottom->z; v = bottom->v;
                            }
                            if (!cat.IsNewDiff(cat.GetNodesSS(y_object),yd,top->v,v,page)) continue;
                            json witness = {{"rule",known_survival ? "source-finite-known-survival" : "source-finite"},{"triangle",triangle.name},
                                {"slot",a},{"r",r},{"K1",k1},{"K2",k2},{"D",page},
                                {"source_degree",{d.s,d.t}},{"x",x},{"u",u},
                                {"z1",top->z},{"z2",z},{"y",top->v},{"v",v},
                                {"whole_top_middle_checked",true},{"whole_correction_image_checked",true},
                                {"whole_bottom_middle_checked",true},{"whole_terminal_kernel_checked",true}};
                            result.push_back({y_object,yd,page,top->v,v,witness.dump()});
                        } catch (const Missing&) { }
                    }
                }
                continue;
            }
            if (!contains(st.boundaries(y_object,target + fm->deg,r),fu)) continue;
            if (!contains(st.cycle_lower(y_object,y_degree,r),y)) continue;
            auto z_degree = target - hm->deg;
            // K is searched, not read from a historical output record.
            for (int k = 2; k <= 12 && r + k - 1 < R_PERM; ++k) {
                try {
                    int page = r + k - 1;
                    auto v_degree = z_degree + AdamsDeg(k, k - 1) - gm->deg;
                    if (v_degree != y_degree + AdamsDeg(page, page - 1)) continue;
                    auto p = st.permanent_upper(y_object, v_degree);
                    auto gp = st.map_space(g, v_degree, p);
                    auto by = st.boundaries(y_object, v_degree, page);
                    Space terminal_kernel;
                    for (auto& rel : kernel(gp)) terminal_kernel.push_back(linear_apply(p, rel));
                    if (!contained(terminal_kernel, by)) continue;
                    bool full_middle = middle(st, object, z_object, target, h, k, false, f, y_object);
                    bool known_survival=false;
                    if (!full_middle && !middle(st, object, z_object, target, h, k, true, f, y_object)) {
                        if (!contains(st.cycle_lower(y_object,y_degree,page),y) ||
                            !middle(st,object,z_object,target,h,k,true,f,y_object,r)) continue;
                        known_survival=true;
                    }
                    auto lift = find_lift(st,h,g,z_object,z_degree,u,k,p,v_degree,
                                         st.boundaries(object,target,r));
                    if (!lift) continue;
                    auto z = lift->z, v = lift->v;
                    if (!cat.IsNewDiff(cat.GetNodesSS(y_object), y_degree, y, v, page)) continue;
                    std::string rule = full_middle ? "finite-zigzag-page" : "selective-middle-page";
                    if (known_survival) rule="known-source-survival";
                    json witness = {{"rule",rule},{"triangle",triangle.name},{"slot",a},
                        {"r",r},{"K",k},{"D",page},{"source_degree",{d.s,d.t}},
                        {"x",x},{"u",u},{"z",z},{"y",y},{"v",v},
                        {"whole_middle_checked",true},{"whole_terminal_kernel_checked",true},
                        {"P_dimension",p.size()},{"early_bound",page}};
                    result.push_back({y_object,y_degree,page,y,v,witness.dump()});
                } catch (const Missing&) { /* Reject incomplete hypotheses. */ }
            }
        } catch (const Missing&) { /* Reject an out-of-range triangle. */ }
    }
    return result;
}
} // namespace validated_syn
