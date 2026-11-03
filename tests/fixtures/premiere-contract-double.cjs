// Copyright (C) 2026 David L F Gaden
// Host-only contract double. Executes the actual companion, never Premiere.
"use strict";
const fs=require("fs"),path=require("path");
const observer=require(path.resolve(process.argv[2]));
const directory=path.resolve(process.argv[3]),mode=process.argv[4]||"valid";
const guid=value=>({toString:()=>value}),tick=value=>({ticks:value});
let reads=0, snapshots=0;
const entry=name=>({name,isFile:true,read:async()=>{
    reads++;
    if(mode==="changed-request" && reads===2) fs.appendFileSync(path.join(directory,name)," ");
    return fs.readFileSync(path.join(directory,name),"utf8");
},write:async value=>{fs.writeFileSync(path.join(directory,name),value);},
moveTo:async(folder,options)=>{fs.renameSync(path.join(directory,name),path.join(directory,options.newName));}});
const folder={getEntries:async()=>fs.readdirSync(directory).map(entry),createFile:async(name)=>entry(name)};
const clips=[
    {sourcePath:"/replace-with-your-media/colours.mp4",start:"0",end:"30481920000",in:"30481920000",out:"60963840000",duration:"30481920000"},
    {sourcePath:"/replace-with-your-media/colours.mp4",start:"30481920000",end:"50803200000",in:"0",out:"20321280000",duration:"20321280000"}
].map((row,index)=>{
    const source={getId:()=>"source-colours",getMediaFilePath:async()=>row.sourcePath,isOffline:async()=>false,isSequence:async()=>false,isMergedClip:async()=>false,isMulticamClip:async()=>false,hasProxy:async()=>false};
    return {getProjectItem:async()=>source,getName:async()=>"colours",getStartTime:async()=>tick(row.start),getEndTime:async()=>tick(row.end),
        getInPoint:async()=>tick(mode==="imprecise-ticks" ? Number(row.in):mode==="high-precision" && index===0 ? "10160640000000000":row.in),
        getOutPoint:async()=>tick(mode==="high-precision" && index===0 ? "10160670481920000":row.out),getDuration:async()=>tick(row.duration),
        isDisabled:async()=>false,isAdjustmentLayer:async()=>false,isSpeedReversed:async()=>0};
});
const track={name:"V1",getTrackItems:(type)=>type===1?(mode==="oversized-track"?Array(129).fill(clips[0]):clips):[],getIndex:async()=>0,isMuted:async()=>false};
const sequence={guid:guid("sequence-guid"),name:"Schemaxis Colours",getFrameSize:async()=>({width:32,height:24}),getVideoTrackCount:async()=>1,getAudioTrackCount:async()=>0,getCaptionTrackCount:async()=>0,getVideoTrack:async()=>{snapshots++;return track;},
    getTimebase:async()=>"10160640000",getZeroPoint:async()=>tick("0"),getEndTime:async()=>tick(mode==="changed-sequence" && snapshots>1?"60000000000":"50803200000")};
const project={guid:guid("project-guid"),name:"colours",path:"/replace-with-your-project/colours.prproj",getActiveSequence:async()=>sequence};
const ppro={Project:{getActiveProject:async()=>project},ClipProjectItem:{cast:value=>value}};
const uxp={host:{name:"premierepro",version:"26.5.0",applicationPath:"/Applications/Adobe Premiere Pro/Adobe Premiere Pro.app"},versions:{uxp:"uxp-9.3.0-local"}};
if(mode==="stale-response") {const request=JSON.parse(fs.readFileSync(path.join(directory,"request.json")));fs.writeFileSync(path.join(directory,request.responseFile),"prior response");}
observer.observeFolder(folder,ppro,uxp).then(response=>process.stdout.write(JSON.stringify(response))).catch(error=>{process.stderr.write(error.message);process.exitCode=1;});
