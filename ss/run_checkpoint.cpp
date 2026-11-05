#include "run_checkpoint.h"
#include "mylog.h"
#include <cstdlib>
#include <fstream>

namespace {
std::string read_file(const std::string& path) {
    std::ifstream f(path); return {std::istreambuf_iterator<char>(f),{}};
}
std::string checkpoint_path(const std::string& root) {return root+"/recovery.sqlite3";}
json raw_config(const std::string& root) {return json::parse(read_file(root+"/ss.json"));}
std::string command_name() {const char* p=std::getenv("SS_RUN_COMMAND");return p?p:"manual";}
}

json RunCheckpoint::Encode(const SS& value) {
    json result={{"shape",json::array()},{"valid_shape",json::array()},{"rows",json::array()}};
    for(size_t n=0;n<value.data_.size();++n) {
        result["shape"].push_back(value.data_[n].size());
        for(size_t s=0;s<value.data_[n].size();++s) {
            const auto& sc=value.data_[n][s];
            auto valid=n<value.valid_.size()&&s<value.valid_[n].size()?value.valid_[n][s]:0;
            if(valid||!sc.basis.empty()||!sc.diffs.empty()||!sc.levels.empty())
                result["rows"].push_back({n,s,valid,sc.basis,sc.diffs,sc.levels});
        }
    }
    for(const auto& row:value.valid_) result["valid_shape"].push_back(row.size());
    return result;
}
SS RunCheckpoint::Decode(const json& value) {
    SS result;
    for(auto n:value.at("shape")) result.data_.emplace_back(n.get<size_t>());
    for(auto n:value.at("valid_shape")) result.valid_.emplace_back(n.get<size_t>(),0);
    for(const auto& row:value.at("rows")) {
        auto n=row[0].get<size_t>(),s=row[1].get<size_t>();
        auto& sc=result.data_.at(n).at(s);
        result.valid_.at(n).at(s)=row[2].get<uint32_t>();
        sc.basis=row[3].get<int2d>();sc.diffs=row[4].get<int2d>();sc.levels=row[5].get<int1d>();
        if(sc.basis.size()!=sc.diffs.size()||sc.basis.size()!=sc.levels.size())
            throw RunTimeError("Invalid recovery staircase");
    }
    return result;
}
json RunCheckpoint::Encode(const Exclusions& value) {
    json result={{"shape",json::array()},{"valid",value.valid_},{"rows",json::array()}};
    for(size_t n=0;n<value.data_.size();++n) {
        result["shape"].push_back(value.data_[n].size());
        for(size_t s=0;s<value.data_[n].size();++s) {
            json entries=json::array();
            for(const auto& e:value.data_[n][s]) entries.push_back({e.x,e.r,e.dxs});
            if(!entries.empty()) result["rows"].push_back({n,s,entries});
        }
    }
    return result;
}
Exclusions RunCheckpoint::DecodeExclusions(const json& value) {
    Exclusions result;
    for(auto n:value.at("shape")) result.data_.emplace_back(n.get<size_t>());
    result.valid_=value.at("valid").get<std::vector<std::vector<uint32_t>>>();
    for(const auto& row:value.at("rows"))
        for(const auto& e:row[2]) result.data_.at(row[0].get<size_t>()).at(row[1].get<size_t>()).push_back({e[0].get<int1d>(),e[1].get<int>(),e[2].get<int2d>()});
    return result;
}
json RunCheckpoint::Encode(const SSNodes& value) {
    if(value.size()!=2) throw RunTimeError("Recovery may only save the outer state, never a trial");
    return {{"layers",{Encode(value[0]),Encode(value[1])}},{"exclusions",Encode(value.exclusions)}};
}
SSNodes RunCheckpoint::DecodeNodes(const json& value) {
    if(value.at("layers").size()!=2) throw RunTimeError("Invalid recovery layer count");
    SSNodes result;
    result.push_back(Decode(value["layers"][0]));result.push_back(Decode(value["layers"][1]));
    result.exclusions=DecodeExclusions(value.at("exclusions"));return result;
}
json RunCheckpoint::Metadata(const std::string& root) {
    if(!std::filesystem::exists(checkpoint_path(root))) throw RunTimeError("No recovery checkpoint exists");
    myio::Database db(checkpoint_path(root));
    return json::parse(db.get_str("SELECT value FROM metadata WHERE id=1"));
}
void RunCheckpoint::Validate(const std::string& root) {
    auto meta=Metadata(root);
    if(meta.at("version")!=1||meta.at("config")!=raw_config(root)||
       meta.at("initial_inputs")!=read_file(root+"/initial-inputs.sha256"))
        throw RunTimeError("Recovery input identity mismatch");
}
void RunCheckpoint::LoadNodes(const std::string& root,const std::string& key,SSNodes& nodes,AdamsDeg1d* degrees) {
    myio::Database db(checkpoint_path(root));
    std::string quoted;
    for(char c:key) {quoted+=c;if(c=='\'')quoted+='\'';}
    auto value=json::parse(db.get_str("SELECT value FROM nodes WHERE name='"+quoted+"'"));nodes=DecodeNodes(value);
    if(degrees) {
        degrees->clear();
        for(auto d:value.at("degrees")) degrees->push_back(AdamsDeg(d[0].get<int>(),d[1].get<int>()));
    }
}
RunCheckpoint::RunCheckpoint(Category& category,std::string root,std::string kind,json options,double seconds,bool resume):
    category_(category),root_(std::move(root)),options_(std::move(options)),seconds_(seconds),
    saved_(std::chrono::steady_clock::now()),published_(saved_) {
    if(category_.depth_!=0) throw RunTimeError("Cannot checkpoint a trial");
    if(resume) {
        Validate(root_);meta_=Metadata(root_);
        if(meta_.at("kind")!=kind||meta_.at("options")!=options_||meta_.at("command")!=command_name())
            throw RunTimeError("Recovery command identity mismatch");
        int floor=meta_.at("log_id");
        if(Logger::GetCheckpoint()<floor) throw RunTimeError("Recovery refers to missing committed log rows");
        Logger::RollBackToCheckpoint(floor);Logger::RollBackToExclusionsCheckpoint(floor);
        Logger::db_.end_transaction();Logger::db_.begin_transaction();
        first_round_=meta_.at("round").get<int>();
        seeking_=!meta_.value("cursor",std::string()).empty()&&!Complete();
    } else {
        if(std::filesystem::exists(checkpoint_path(root_))) {
            myio::Database previous(checkpoint_path(root_));
            // SQLite may leave an empty file if the very first save is killed.
            if(previous.has_table("metadata")&&!Metadata(root_).value("complete",false))
                throw RunTimeError("Unfinished recovery exists; use checkpoint_resume=1");
        }
        meta_={{"version",1},{"kind",kind},{"options",options_},{"command",command_name()},
               {"config",raw_config(root_)},{"initial_inputs",read_file(root_+"/initial-inputs.sha256")},
               {"round",1},{"round_start",Logger::GetCheckpoint()},{"cursor",""},
               {"changed",false},{"command_code",0},{"complete",false},{"sequence",0}};
        Write();
    }
}
void RunCheckpoint::BeginRound(int round) {
    if(round!=meta_.at("round").get<int>()) {
        meta_["round"]=round;meta_["round_start"]=Logger::GetCheckpoint();
        meta_["cursor"]="";meta_["changed"]=false;
        Write();
    }
}
SSRet RunCheckpoint::Step(const std::string& key,const std::function<SSRet()>& operation) {
    if(category_.depth_!=0) throw RunTimeError("Checkpoint step entered inside a trial");
    if(seeking_) {
        if(key==meta_.at("cursor").get<std::string>()) seeking_=false;
        return SSRet::NUL();
    }
    auto result=operation();if(result) return result;
    if(category_.depth_!=0) throw RunTimeError("Trial did not unwind before checkpoint");
    meta_["cursor"]=key;meta_["changed"]=Changed()||result.IsChanged();
    meta_["command_code"]=std::max(AccumulatedCode(),result.code);
    auto now=std::chrono::steady_clock::now();
    if(seconds_>0&&std::chrono::duration<double>(now-saved_).count()>=seconds_) Write();
    else if(std::chrono::duration<double>(now-published_).count()>=30) Publish();
    return result;
}
void RunCheckpoint::EndRound() {
    if(seeking_) throw RunTimeError("Recovery cursor was not found in the resumed scan");
}
void RunCheckpoint::Publish() {
    Logger::db_.end_transaction();
    auto rows=Logger::db_.get_int("SELECT count(*) FROM log");
    auto id=Logger::GetCheckpoint();
    Logger::db_.begin_transaction();published_=std::chrono::steady_clock::now();
    fmt::print("\nSS_PROGRESS {}\n",json({{"log_rows",rows},{"log_id",id},
        {"recoverable_log_rows",meta_.value("log_rows",0)},
        {"recoverable_log_id",meta_.value("log_id",0)},{"checkpoint_sequence",meta_.at("sequence")},
        {"round",meta_.at("round")},{"complete",Complete()}}).dump());
    std::fflush(stdout);
}
void RunCheckpoint::Write() {
    if(category_.depth_!=0) throw RunTimeError("Cannot save a trial");
    Logger::db_.end_transaction();
    auto next=meta_;next["log_id"]=Logger::GetCheckpoint();
    next["log_rows"]=Logger::db_.get_int("SELECT count(*) FROM log");
    next["sequence"]=meta_.at("sequence").get<int>()+1;
    if(const char* p=std::getenv("SS_BINARY_SHA256")) next["binary_sha256"]=p;
    if(const char* p=std::getenv("SS_SOURCE_COMMIT")) next["source_commit"]=p;
    myio::Database db(checkpoint_path(root_));
    db.execute_cmd("PRAGMA synchronous=FULL");db.begin_transaction();
    try {
    db.execute_cmd("CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY,value TEXT NOT NULL)");
    db.execute_cmd("CREATE TABLE IF NOT EXISTS nodes(name TEXT PRIMARY KEY,value TEXT NOT NULL)");
    db.execute_cmd("DELETE FROM nodes");
    myio::Statement insert(db,"INSERT INTO nodes VALUES(?1,?2)");
    auto write=[&](std::string name,const SSNodes& nodes,const AdamsDeg1d* degrees=nullptr) {
        auto value=Encode(nodes);
        if(degrees) {value["degrees"]=json::array();for(auto d:*degrees)value["degrees"].push_back({d.s,d.t});}
        insert.bind_and_step(name,value.dump());
    };
    for(const auto& ring:category_.rings_) write(ring.name,ring.nodes_ss,&ring.degs_ss);
    for(const auto& mod:category_.modules_) write(mod.name,mod.nodes_ss,&mod.degs_ss);
    for(const auto& cof:category_.cofseqs_) for(size_t i=0;i<3;++i) write(cof.name+":"+std::to_string(i),cof.nodes_cofseq[i]);
    myio::Statement metadata(db,"INSERT OR REPLACE INTO metadata VALUES(1,?1)");metadata.bind_and_step(next.dump());
    db.end_transaction();
    } catch(...) {db.rollback_transaction();Logger::db_.begin_transaction();throw;}
    meta_=std::move(next);saved_=std::chrono::steady_clock::now();
    Logger::db_.begin_transaction();Publish();
}
void RunCheckpoint::Finish() {EndRound();meta_["complete"]=true;Write();}
SSRet Category::CheckpointStep(const std::string& key,const std::function<SSRet()>& operation) {
    return run_checkpoint_?run_checkpoint_->Step(key,operation):operation();
}
std::shared_ptr<RunCheckpoint> Category::EnableCheckpoints(const std::string& root,const std::string& kind,const json& options,double seconds,bool resume) {
    if(seconds<0 || (resume&&seconds==0)) throw RunTimeError("Invalid checkpoint interval");
    if(seconds>0) run_checkpoint_=std::make_shared<RunCheckpoint>(*this,root,kind,options,seconds,resume);
    return run_checkpoint_;
}
