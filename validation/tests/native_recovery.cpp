#include "../../ss/run_checkpoint.h"
#include "../../ss/mylog.h"
#include <iostream>

static void require(bool value,const char* message) {if(!value)throw std::runtime_error(message);}
static auto payloads(const std::string& root) {
    myio::Database db(root+"/recovery.sqlite3");
    myio::Statement q(db,"SELECT name,value FROM nodes ORDER BY name");
    std::map<std::string,std::string> result;
    while(q.step()==MYSQLITE_ROW)result.emplace(q.column_str(0),q.column_str(1));
    return result;
}
int main(int argc,char** argv) {
    require(argc==2,"fixture required");std::string root=argv[1];
    Logger::SetOutDeduce((root+"/log.db").c_str());
    const auto flags=SSFlag::cofseq;
    Category cat(root,"",flags,false);
    {myio::Database unpublished(root+"/recovery.sqlite3");}
    auto cp=cat.EnableCheckpoints(root,"unit",json::object(),1e-9,false);
    auto object=cat.GetIndexCwByName("S0");auto d=AdamsDeg(9,132);
    auto& nodes=cat.GetNodesSS(object);
    nodes.back()[d]=nodes.GetRecentSc(d);
    nodes.front().Sync(d);nodes.back().Sync(d);
    nodes.back().resize(nodes.front().size()+2);
    nodes.exclusions.get(d,{0},7).dxs={{0},{1}};
    auto result=cat.CheckpointStep("done-degree",[]{return SSRet::CHANGE();});
    require(result.IsChanged(),"step result lost");
    auto before=payloads(root);
    // A later committed log tail is not a recovery input. It is discarded.
    Logger::db_.InsertInfo(-3,"tail after the checkpoint");Logger::db_.end_transaction();Logger::db_.begin_transaction();
    Category restored(root,"",flags,false,false,true);
    auto recovery=restored.EnableCheckpoints(root,"unit",json::object(),1e-9,true);
    require(Logger::GetCheckpoint()==RunCheckpoint::Metadata(root)["log_id"].get<int>(),"log tail not trimmed");
    (void)restored.CheckpointStep("done-degree",[]{throw std::runtime_error("completed step repeated");return SSRet::NUL();});
    (void)restored.CheckpointStep("next-degree",[]{return SSRet::NUL();});
    require(payloads(root)==before,"layers, flags, shapes or exclusion cache changed on restore");
    auto stable=RunCheckpoint::Metadata(root);auto stable_payloads=payloads(root);
    // Throw after DELETE FROM nodes to test explicit rollback, not the wrapper's
    // default commit-on-destruction behavior.
    restored.GetNodesSS(object).push_back({});
    bool failed=false;
    try {(void)restored.CheckpointStep("invalid",[]{return SSRet::NUL();});}
    catch(const std::exception&) {failed=true;}
    require(failed,"invalid snapshot should fail");restored.GetNodesSS(object).pop_back();
    require(RunCheckpoint::Metadata(root)==stable&&payloads(root)==stable_payloads,"failed save replaced good checkpoint");
    restored.AddNode(flags);failed=false;
    try {(void)restored.CheckpointStep("trial",[]{return SSRet::NUL();});}
    catch(const std::exception&) {failed=true;}
    restored.PopNode(flags);
    require(failed&&RunCheckpoint::Metadata(root)==stable,"trial state was saved");
    std::cout<<"PASS: exact layer/flag/cache roundtrip, log truncation, failed-save rollback, trial refusal\n";
}
