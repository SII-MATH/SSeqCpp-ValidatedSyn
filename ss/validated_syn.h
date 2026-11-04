#pragma once
#include "main.h"

// A candidate is accepted only after all finite-comparison hypotheses pass.
// The engine never reads a target list, historical event, or old Syn image.
namespace validated_syn {
struct Conclusion {
    IndexUniv object;
    AdamsDeg source;
    int page;
    int1d x, y;
    std::string witness;
};
std::vector<Conclusion> finite_zigzags(Category&, IndexUniv, AdamsDeg,
                                     const int1d&, const int1d&, int);
}
