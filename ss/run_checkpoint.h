#pragma once
#include "main.h"
#include <chrono>

// A recovery cache for this fresh run, not an additional inference input.
class RunCheckpoint {
    Category& category_;
    std::string root_;
    json meta_,options_;
    double seconds_;
    std::chrono::steady_clock::time_point saved_,published_;
    bool seeking_=false;
    int first_round_=1;
    static json Encode(const SS& value);
    static SS Decode(const json& value);
    static json Encode(const Exclusions& value);
    static Exclusions DecodeExclusions(const json& value);
    static json Encode(const SSNodes& value);
    static SSNodes DecodeNodes(const json& value);
    void Write();
    void Publish();
public:
    RunCheckpoint(Category&,std::string root,std::string kind,json options,double seconds,bool resume);
    static json Metadata(const std::string& root);
    static void LoadNodes(const std::string& root,const std::string& key,SSNodes&,AdamsDeg1d* degrees=nullptr);
    static void Validate(const std::string& root);
    int FirstRound() const {return first_round_;}
    bool Complete() const {return meta_.value("complete",false);}
    bool Changed() const {return meta_.value("changed",false);}
    unsigned AccumulatedCode() const {return meta_.value("command_code",0u);}
    int RoundStart() const {return meta_.at("round_start").get<int>();}
    void BeginRound(int round);
    SSRet Step(const std::string&,const std::function<SSRet()>&);
    void EndRound();
    void Finish();
};
