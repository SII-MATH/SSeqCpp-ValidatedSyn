#include "validated_syn.h"
/* This module deals with operations that might affect all spectra */

#include "algebras/linalg.h"
#include "main.h"
#include "mylog.h"

/* Add a node */
void Category::AddNode(SSFlag flag)
{
    ++depth_;
    for (auto& ring : rings_)
        ring.nodes_ss.AddNode();
    for (auto& mod : modules_)
        mod.nodes_ss.AddNode();
    if (flag & SSFlag::cofseq) {
        for (auto& cofseq : cofseqs_)
            for (size_t iTri = 0; iTri < 3; ++iTri)
                cofseq.nodes_cofseq[iTri].AddNode();
    }

    if (flag & SSFlag::pi) {
        for (auto& ring : rings_) {
            ring.pi_gb.AddNode();
            ring.nodes_pi_basis.push_back({});
        }
        for (auto& mod : modules_) {
            mod.pi_gb.AddNode();
            mod.nodes_pi_basis.push_back({});
        }

        //// TODO: Add pi_maps
    }
}

/* Pop the lastest node */
void Category::PopNode(SSFlag flag)
{
    --depth_;
    for (auto& ring : rings_)
        ring.nodes_ss.pop_back();
    for (auto& mod : modules_)
        mod.nodes_ss.pop_back();
    if (flag & SSFlag::cofseq) {
        for (auto& cofseq : cofseqs_)
            for (size_t iTri = 0; iTri < 3; ++iTri)
                cofseq.nodes_cofseq[iTri].pop_back();
    }

    if (flag & SSFlag::pi) {
        for (auto& ring : rings_) {
            ring.pi_gb.PopNode();
            ring.nodes_pi_basis.pop_back();
        }
        for (auto& mod : modules_) {
            mod.pi_gb.PopNode();
            mod.nodes_pi_basis.pop_back();
        }
        //// TODO: Add pi_maps
        // UpdateAllPossEinf();
    }
}

int1d MapRing2Ring::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& rings = category.GetRings();
        auto x_alg = Indices2Poly(x, rings[from.index].basis.at(deg_x));
        auto fx_alg = rings[to.index].gb.Reduce(subs(x_alg, images));
        if (fx_alg)
            result = Poly2Indices(fx_alg, rings[to.index].basis.at(deg_x));
    }
    return result;
}

int1d MapMod2Mod::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& mods = category.GetModules();
        auto x_alg = Indices2Mod(x, mods[from.index].basis.at(deg_x));
        auto fx_alg = mods[to.index].gb.Reduce(subs(x_alg, images));
        if (fx_alg) {
            AdamsDeg deg_fx = deg_x + deg;
            result = Mod2Indices(fx_alg, mods[to.index].basis.at(deg_fx));
        }
    }
    return result;
}

void MapMod2Mod::Verify(const Category& category, const AdamsDeg2d& ring_gen_degs)
{
    fmt::print("Verifying {}\n", name);
    auto& mods = category.GetModules();
    auto& gen_degs = ring_gen_degs[mods[from.index].iRing];
    for (AdamsDeg deg_x : mods[from.index].degs_ss) {
        auto& basis_d = mods[from.index].basis.at(deg_x);
        for (size_t g = 0; g < gen_degs.size(); ++g) {
            AdamsDeg deg_gx = deg_x + gen_degs[g];
            if (deg_gx.t > t_max)
                break;
            Poly poly_g = Poly::Gen((uint32_t)g);
            for (size_t i = 0; i < basis_d.size(); ++i) {
                Mod alg_gx = mods[from.index].gb.Reduce(poly_g * basis_d[i]);
                int1d gx = alg_gx ? Mod2Indices(alg_gx, mods[from.index].basis.at(deg_gx)) : int1d{};
                int1d fgx = map(gx, deg_gx, category);
                int1d fx = map(int1d{(int)i}, deg_x, category);
                Mod alg_fx = fx.empty() ? Mod() : Indices2Mod(fx, mods[to.index].basis.at(deg_x + deg));
                Mod alg_gfx = mods[to.index].gb.Reduce(poly_g * alg_fx);
                int1d gfx = alg_gfx ? Mod2Indices(alg_gfx, mods[to.index].basis.at(deg_gx + deg)) : int1d{};
                if (fgx != gfx) {
                    fmt::print("Incorrect map: {} deg_x={}, x={}, deg_g={}, g={}\n", name, deg_x, i, gen_degs[g], poly_g.Str());
                    throw ErrorIdMsg(0x18a1700f, "Incorrect map");
                }
            }
        }
    }
}

auto subs(const Mod& x, const Poly1d& map1, const Mod1d& map2)
{
    Mod result{}, tmp{};
    Poly tmp_prod_p, tmf_p;
    for (const MMod& m : x.data) {
        Poly fm = Poly::Unit();
        for (auto p = m.m.begin(); p != m.m.end(); ++p) {
            powP(map1[p->g()], p->e_masked(), tmp_prod_p, tmf_p);
            fm.imulP(tmp_prod_p, tmf_p);
        }
        result.iaddP(fm * map2[m.v], tmp);
    }
    return result;
}

int1d MapMod2ModV2::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& mods = category.GetModules();
        auto& maps = category.GetMaps();
        auto x_alg = Indices2Mod(x, mods[from.index].basis.at(deg_x));
        auto fx_alg = mods[to.index].gb.Reduce(subs(x_alg, ((MapRing2Ring*)maps[over].get())->images, images));
        if (fx_alg) {
            AdamsDeg deg_fx = deg_x + deg;
            result = Mod2Indices(fx_alg, mods[to.index].basis.at(deg_fx));
        }
    }
    return result;
}

void MapMod2ModV2::Verify(const Category& category, const AdamsDeg2d& ring_gen_degs)
{
    fmt::print("Verifying {}\n", name);
    auto& mods = category.GetModules();
    auto& maps = category.GetMaps();
    auto& gen_degs = ring_gen_degs[mods[from.index].iRing];
    for (AdamsDeg deg_x : mods[from.index].degs_ss) {
        auto& basis_d = mods[from.index].basis.at(deg_x);
        for (size_t g = 0; g < gen_degs.size(); ++g) {
            AdamsDeg deg_gx = deg_x + gen_degs[g];
            if (deg_gx.t > t_max)
                break;
            Poly poly_g = Poly::Gen((uint32_t)g);
            Poly poly_fg = ((MapRing2Ring*)maps[over].get())->images[g];
            for (size_t i = 0; i < basis_d.size(); ++i) {
                Mod alg_gx = mods[from.index].gb.Reduce(poly_g * basis_d[i]);
                int1d gx = alg_gx ? Mod2Indices(alg_gx, mods[from.index].basis.at(deg_gx)) : int1d{};
                int1d fgx = map(gx, deg_gx, category);
                int1d fx = map(int1d{(int)i}, deg_x, category);
                Mod alg_fx = fx.empty() ? Mod() : Indices2Mod(fx, mods[to.index].basis.at(deg_x + deg));
                Mod alg_fgfx = mods[to.index].gb.Reduce(poly_fg * alg_fx);
                int1d fgfx = alg_fgfx ? Mod2Indices(alg_fgfx, mods[to.index].basis.at(deg_gx + deg)) : int1d{};
                if (fgx != fgfx) {
                    fmt::print("Incorrect map: {} deg_x={}, x={}, deg_g={}, g={}\n", name, deg_x, i, gen_degs[g], poly_g.Str());
                    throw ErrorIdMsg(0x18a1700f, "Incorrect map");
                }
            }
        }
    }
}

int1d MapMod2Ring::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& rings = category.GetRings();
        auto& mods = category.GetModules();
        auto x_alg = Indices2Mod(x, mods[from.index].basis.at(deg_x));
        auto fx_alg = rings[to.index].gb.Reduce(subs(x_alg, images));
        if (fx_alg) {
            AdamsDeg deg_fx = deg_x + deg;
            result = Poly2Indices(fx_alg, rings[to.index].basis.at(deg_fx));
        }
    }
    return result;
}

void MapMod2Ring::Verify(const Category& category, const AdamsDeg2d& ring_gen_degs)
{
    fmt::print("Verifying {}\n", name);
    auto& mods = category.GetModules();
    auto& rings = category.GetRings();
    auto& gen_degs = ring_gen_degs[mods[from.index].iRing];
    for (AdamsDeg deg_x : mods[from.index].degs_ss) {
        auto& basis_d = mods[from.index].basis.at(deg_x);
        for (size_t g = 0; g < gen_degs.size(); ++g) {
            AdamsDeg deg_gx = deg_x + gen_degs[g];
            if (deg_gx.t > t_max)
                break;
            Poly poly_g = Poly::Gen((uint32_t)g);
            for (size_t i = 0; i < basis_d.size(); ++i) {
                Mod alg_gx = mods[from.index].gb.Reduce(poly_g * basis_d[i]);
                int1d gx = alg_gx ? Mod2Indices(alg_gx, mods[from.index].basis.at(deg_gx)) : int1d{};
                int1d fgx = map(gx, deg_gx, category);
                int1d fx = map(int1d{(int)i}, deg_x, category);
                auto alg_fx = fx.empty() ? Poly() : Indices2Poly(fx, rings[to.index].basis.at(deg_x + deg));
                auto alg_gfx = rings[to.index].gb.Reduce(poly_g * alg_fx);
                int1d gfx = alg_gfx ? Poly2Indices(alg_gfx, rings[to.index].basis.at(deg_gx + deg)) : int1d{};
                if (fgx != gfx) {
                    fmt::print("Incorrect map: {} deg_x={}, x={}, deg_g={}, g={}\n", name, deg_x, i, gen_degs[g], poly_g.Str());
                    throw ErrorIdMsg(0x18a1700f, "Incorrect map");
                }
            }
        }
    }
}

auto subs(const Mod& x, const Poly1d& map1, const Poly1d& map2)
{
    Poly result, tmp_prod, tmp;
    for (const MMod& m : x.data) {
        Poly fm = Poly::Unit();
        for (auto p = m.m.begin(); p != m.m.end(); ++p) {
            powP(map1[p->g()], p->e_masked(), tmp_prod, tmp);
            fm.imulP(tmp_prod, tmp);
        }
        result.iaddP(fm * map2[m.v], tmp);
    }
    return result;
}

int1d MapMod2RingV2::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& rings = category.GetRings();
        auto& mods = category.GetModules();
        auto& maps = category.GetMaps();
        auto x_alg = Indices2Mod(x, mods[from.index].basis.at(deg_x));
        auto fx_alg = rings[to.index].gb.Reduce(subs(x_alg, ((MapRing2Ring*)maps[over].get())->images, images));
        if (fx_alg) {
            AdamsDeg deg_fx = deg_x + deg;
            result = Poly2Indices(fx_alg, rings[to.index].basis.at(deg_fx));
        }
    }
    return result;
}

void MapMod2RingV2::Verify(const Category& category, const AdamsDeg2d& ring_gen_degs)
{
    fmt::print("Verifying {}\n", name);
    auto& mods = category.GetModules();
    auto& rings = category.GetRings();
    auto& maps = category.GetMaps();
    auto& gen_degs = ring_gen_degs[mods[from.index].iRing];
    for (AdamsDeg deg_x : mods[from.index].degs_ss) {
        auto& basis_d = mods[from.index].basis.at(deg_x);
        for (size_t g = 0; g < gen_degs.size(); ++g) {
            AdamsDeg deg_gx = deg_x + gen_degs[g];
            if (deg_gx.t > t_max)
                break;
            Poly poly_g = Poly::Gen((uint32_t)g);
            Poly poly_fg = ((MapRing2Ring*)maps[over].get())->images[g];
            for (size_t i = 0; i < basis_d.size(); ++i) {
                Mod alg_gx = mods[from.index].gb.Reduce(poly_g * basis_d[i]);
                int1d gx = alg_gx ? Mod2Indices(alg_gx, mods[from.index].basis.at(deg_gx)) : int1d{};
                int1d fgx = map(gx, deg_gx, category);
                int1d fx = map(int1d{(int)i}, deg_x, category);
                auto alg_fx = fx.empty() ? Poly() : Indices2Poly(fx, rings[to.index].basis.at(deg_x + deg));
                auto alg_fgfx = rings[to.index].gb.Reduce(poly_fg * alg_fx);
                int1d fgfx = alg_fgfx ? Poly2Indices(alg_fgfx, rings[to.index].basis.at(deg_gx + deg)) : int1d{};
                if (fgx != fgfx) {
                    fmt::print("Incorrect map: {} deg_x={}, x={}, deg_g={}, g={}\n", name, deg_x, i, gen_degs[g], poly_g.Str());
                    throw ErrorIdMsg(0x18a1700f, "Incorrect map");
                }
            }
        }
    }
}

int1d MapMulRing2Ring::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& rings = category.GetRings();
        auto x_alg = Indices2Poly(x, rings[from.index].basis.at(deg_x));
        auto fx_alg = rings[to.index].gb.Reduce(x_alg * factor);
        if (fx_alg) {
            AdamsDeg deg_fx = deg_x + deg;
            result = Poly2Indices(fx_alg, rings[to.index].basis.at(deg_fx));
        }
    }
    return result;
}

int1d MapMulRing2Mod::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& rings = category.GetRings();
        auto& mods = category.GetModules();
        auto x_alg = Indices2Poly(x, rings[from.index].basis.at(deg_x));
        auto fx_alg = mods[to.index].gb.Reduce(x_alg * factor);
        if (fx_alg) {
            AdamsDeg deg_fx = deg_x + deg;
            result = Mod2Indices(fx_alg, mods[to.index].basis.at(deg_fx));
        }
    }
    return result;
}

int1d MapMulMod2Mod::map(const int1d& x, AdamsDeg deg_x, const Category& category) const
{
    int1d result;
    if (!x.empty()) {
        auto& mods = category.GetModules();
        auto x_alg = Indices2Mod(x, mods[from.index].basis.at(deg_x));
        auto fx_alg = mods[to.index].gb.Reduce(factor * x_alg);
        if (fx_alg) {
            AdamsDeg deg_fx = deg_x + deg;
            result = Mod2Indices(fx_alg, mods[to.index].basis.at(deg_fx));
        }
    }
    return result;
}

SSRet Category::SetRingDiffGlobal(size_t iRing, AdamsDeg deg_x, const int1d& x, const int1d& dx, int r, bool newCertain, SSFlag flag)
{
    SSRet rt;
    auto& ring = rings_[iRing];
    auto& nodes_ss = ring.nodes_ss;

    if (newCertain || IsNewDiff(nodes_ss, deg_x, x, dx, r)) {
        int depth = depth_;
        AdamsDeg deg_dx = deg_x + AdamsDeg{r, r - 1};
        if (x.empty()) {
            if (rt += SetRingBoundaryLeibniz(iRing, deg_dx, dx, r - 1, flag))
                return rt;
        }
        else {
            int r_min = LEVEL_MIN;
            while (r_min < r && !IsNewDiff(nodes_ss, deg_x, x, {}, r_min))  // TODO: improve this
                ++r_min;
            if (dx.empty())
                r = NextRTgt(nodes_ss, ring.t_max, deg_x, r + 1) - 1;
            if (rt += SetRingDiffLeibniz(iRing, deg_x, x, dx, r, r_min, flag))
                return rt;
        }

        for (size_t iMap : ring.ind_maps) {
            auto map = (MapRing2Ring*)maps_[iMap].get();
            if (deg_x.t <= map->t_max) {
                int1d fdx;
                if (deg_dx.t <= map->t_max)
                    fdx = map->map(dx, deg_dx, *this);
                else if (!dx.empty())
                    continue;
                auto fx = map->map(x, deg_x, *this);
                if (IsNewDiff(rings_[map->to.index].nodes_ss, deg_x, fx, fdx, r)) {
                    Logger::LogDiff(depth, EnumReason::nat, rings_[map->to.index].name, deg_x, r, fx, fdx, map->name, flag);
                    if (rt += SetCwDiffGlobal(map->to, deg_x, fx, fdx, r, true, flag | SSFlag::stacked)) {
                        if (flag & SSFlag::log_proof)
                            rt.err_msg = fmt::format("Get `{} {} d_{}[{}]=[{}]`. Consider the map `{}`.\n{}", rings_[iRing].name, deg_x, r, myio::Serialize(x), myio::Serialize(dx), map->name, rt.err_msg);
                        return rt;
                    }
                }
            }
        }

        /* x^2 are cycles in E_r */
        auto deg_xx = deg_x * 2;
        if (deg_xx.t <= ring.t_max && !x.empty() && dx.empty() && r < R_PERM - 1) {
            Poly poly_x = Indices2Poly(x, ring.basis.at(deg_x));
            Poly poly_xx;
            poly_x.frobP(poly_xx);
            poly_xx = ring.gb.Reduce(std::move(poly_xx));
            if (poly_xx) {
                int1d xx = Poly2Indices(poly_xx, ring.basis.at(deg_xx));
                if (IsNewDiff(nodes_ss, deg_xx, xx, {}, r + 1)) {
                    Logger::LogDiff(depth, EnumReason::deduce_xx, ring.name, deg_xx, r + 1, xx, {}, "", flag);
                    if (rt += SetRingDiffGlobal(iRing, deg_xx, xx, {}, r + 1, true, flag | SSFlag::stacked)) {
                        if (flag & SSFlag::log_proof)
                            rt.err_msg = fmt::format("Consider the square of `{} {} [{}]`", rings_[iRing].name, deg_x, myio::Serialize(x));
                        return rt;
                    }
                }
            }
        }
    }
    if ((flag & SSFlag::cofseq) && !(flag & SSFlag::stacked)) {
        if (rt += SyncToCofseq(flag))
            return rt;
    }
    return rt;
}

SSRet Category::SetModuleDiffGlobal(size_t iMod, AdamsDeg deg_x, const int1d& x, const int1d& dx, int r, bool newCertain, SSFlag flag)
{
    SSRet rt;
    auto& mod = modules_[iMod];
    auto& nodes_ss = mod.nodes_ss;
    int t_max = mod.t_max;

    if (newCertain || IsNewDiff(nodes_ss, deg_x, x, dx, r)) {
        AdamsDeg deg_dx = deg_x + AdamsDeg(r, r - 1);
        if (x.empty()) {
            if (rt += SetModuleBoundaryLeibniz(iMod, deg_dx, dx, r - 1, flag))
                return rt;
        }
        else {
            int r_min = LEVEL_MIN;
            while (r_min < r && !IsNewDiff(nodes_ss, deg_x, x, {}, r_min))  // TODO: improve this
                ++r_min;
            if (dx.empty())
                r = NextRTgt(nodes_ss, t_max, deg_x, r + 1) - 1;
            if (rt += SetModuleDiffLeibniz(iMod, deg_x, x, dx, r, r_min, flag))
                return rt;
        }

        for (size_t iMap : mod.ind_maps) {
            auto& map = maps_[iMap];
            if (deg_x.t <= map->t_max) {
                int1d fdx;
                if (deg_dx.t <= map->t_max)
                    fdx = map->map(dx, deg_dx, *this);
                else if (!dx.empty())
                    continue;
                auto fx = map->map(x, deg_x, *this);
                AdamsDeg deg_fx = deg_x + map->deg;
                if (IsNewDiff(GetNodesSS(map->to), deg_fx, fx, fdx, r)) {
                    Logger::LogDiff(depth_, EnumReason::nat, GetCwName(map->to), deg_fx, r, fx, fdx, map->name, flag);
                    if (rt += SetCwDiffGlobal(map->to, deg_fx, fx, fdx, r, true, flag | SSFlag::stacked)) {
                        if (flag & SSFlag::log_proof)
                            rt.err_msg = fmt::format("Get `{} {} d_{}[{}]=[{}]`. Consider the map `{}`.\n{}", mod.name, deg_x, r, myio::Serialize(x), myio::Serialize(dx), map->name, rt.err_msg);
                        return rt;
                    }
                }
            }
        }
    }
    if ((flag & SSFlag::cofseq) && !(flag & SSFlag::stacked)) {
        if (rt += SyncToCofseq(flag))
            return rt;
    }
    return rt;
}

SSRet Category::SetCwDiffGlobal(IndexUniv iCw, AdamsDeg deg_x, const int1d& x, const int1d& dx, int r, bool newCertain, SSFlag flag)  //// TODO: write two functions into one
{
    SSRet rt;
    if (iCw.isRing())
        rt += SetRingDiffGlobal(iCw.index, deg_x, x, dx, r, newCertain, flag);
    else
        rt += SetModuleDiffGlobal(iCw.index, deg_x, x, dx, r, newCertain, flag);
    if (rt)
        return rt;
    if (depth_ <= 1 && (flag & SSFlag::synthetic) && r <= 6 && x.size() && dx != NULL_DIFF && dx.size()) {
        bool has_cross = GetCrossR(GetNodesSS(iCw), deg_x, GetTMax(iCw), r) <= r;
        if (rt += SetCwDiffSynthetic(iCw, deg_x, x, dx, r, has_cross, flag))
            return rt;
    }
    return rt;
}

/* */
SSRet Category::SetCwDiffSynthetic(IndexUniv iCw, AdamsDeg deg_x, const int1d& x, const int1d& dx, int r, bool, SSFlag flag)
{
    SSRet result;
    for (const auto& conclusion : validated_syn::finite_zigzags(*this, iCw, deg_x, x, dx, r)) {
        if (!IsNewDiff(GetNodesSS(conclusion.object), conclusion.source, conclusion.x, conclusion.y, conclusion.page)) continue;
        Logger::LogDiff(depth_, EnumReason::syn, GetCwName(conclusion.object), conclusion.source,
                        conclusion.page, conclusion.x, conclusion.y, conclusion.witness, flag);
        auto rt = SetCwDiffGlobal(conclusion.object, conclusion.source, conclusion.x,
                                  conclusion.y, conclusion.page, true, flag);
        result += rt;
        if (rt) return result;
        result += SSRet::CHANGE();
    }
    return result;
}

int Category::GetSynImage(IndexUniv, AdamsDeg, const int1d&, int, AdamsDeg&, int1d&, int, int)
{
    throw RunTimeError("Legacy GetSynImage is disabled; use a validated sufficient-condition rule");
}
