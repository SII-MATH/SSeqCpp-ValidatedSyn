#include "main.h"
#include "mylog.h"
#include <fstream>

int main_verify_validated(int argc, char** argv, int& index, const char* desc)
{
    std::string category, target_file;
    bool checkpoint = false;
    myio::CmdArg1d args = {{"category", &category}, {"targets", &target_file}};
    myio::CmdArg1d optional = {{"checkpoint", &checkpoint}};
    if (int error = myio::ParseArguments(argc, argv, index, PROGRAM, desc, VERSION, args, optional)) return error;
    json targets;
    std::ifstream input(target_file);
    if (!input) throw RunTimeError("Cannot open acceptance targets");
    input >> targets;
    if (targets.at("count") != 201 || targets.at("targets").size() != 201)
        throw RunTimeError("Expected exactly 201 targets");
    // Loading saved output is allowed only in this separate verification command.
    // No conclusion is injected. Negative trials are rolled back by TryDiff.
    SSFlag flags = SSFlag::cofseq | SSFlag::synthetic | SSFlag::log_proof |
                   SSFlag::deduce_zero | SSFlag::deduce_pullback |
                   SSFlag::no_exclusions | SSFlag::no_save;
    // Verification may search for a contradiction, but its target-directed
    // trials must never seed exclusions consumed by a later deduction round.
    // A monitor verifies a private, consistent copy of the recovery database.
    // Its own log and rolled-back trials never touch the running calculation.
    Category cat(category, "", flags, true, false, checkpoint);
    json passed = json::array(), missing = json::array(), errors = json::array();
    for (const auto& row : targets.at("targets")) {
        bool okay = false;
        try {
            auto object = cat.GetIndexCwByName(row.at("object"));
            if (object.index == size_t(-1)) throw RunTimeError("Missing target object");
            AdamsDeg d(row.at("s"), row.at("t"));
            int page = row.at("r");
            auto x = row.at("x").get<int1d>(), y = row.at("y").get<int1d>();
            const std::string kind = row.at("kind");
            auto& nodes = cat.GetNodesSS(object);
            if (d.s < 0 || d.stem() < 0 || d.t > cat.GetTMax(object) || !nodes.front().has(d))
                throw RunTimeError("Target is outside available source data");
            if (kind == "equation")
                okay = !cat.IsNewDiff(nodes, d, x, y, page);
            else if (kind == "reaches")
                okay = page >= 2 && !cat.IsNewDiff(nodes, d, x, {}, page - 1);
            else if (kind == "boundaryBy")
                okay = !cat.IsNewDiff(nodes, d - AdamsDeg(page + 1, page), {}, x, page + 1);
            else if (kind == "refutation")
                okay = bool(cat.TryDiff(object, d, x, y, page, flags, true));
            else throw RunTimeError("Unsupported target kind");
        } catch (const std::exception& e) {
            errors.push_back({{"id",row.at("id")},{"message",e.what()}});
        }
        (okay ? passed : missing).push_back(row.at("id"));
    }
    // The log is produced by this fresh run, not the historical proofs database.
    int forbidden = 0;
    myio::Statement query(Logger::db_, "SELECT count(*) FROM log WHERE reason IN ('Syn','SynCs','SynCsIn')");
    if (query.step() == MYSQLITE_ROW) forbidden = query.column_int(0);
    json result = {{"total",201},{"passed",passed.size()},{"missing",missing},
                   {"errors",errors},{"forbidden_outputs",forbidden},
                   {"negative_check","fresh contradiction trials; no absence-as-refutation"}};
    std::ofstream output(category + "/acceptance.json");
    output << result.dump(2) << '\n';
    fmt::print("{}\n", result.dump());
    return passed.size() == 201 && errors.empty() && forbidden == 0 ? 0 : 1;
}
