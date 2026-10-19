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
const variant=mode==="variant";
const rows=[
    [{start:"0",end:"40642560000",in:"0",out:"40642560000",duration:"40642560000"},
     {start:"60963840000",end:"101606400000",in:"20321280000",out:"60963840000",duration:"40642560000"}],
    [variant ? {start:"40642560000",end:"60963840000",in:"10160640000",out:"30481920000",duration:"20321280000"}
     : {start:"30481920000",end:"71124480000",in:"0",out:"40642560000",duration:"40642560000"}], []
];
const tracks=rows.map((values,index)=>{
    const clips=values.map(row=>{
        const source={getId:()=>"source-colours",getMediaFilePath:async()=>"/replace-with-your-media/colours.mp4",isOffline:async()=>false,isSequence:async()=>false,isMergedClip:async()=>false,isMulticamClip:async()=>false,hasProxy:async()=>false};
        return {getProjectItem:async()=>source,getName:async()=>"colours",getStartTime:async()=>tick(row.start),getEndTime:async()=>tick(row.end),
            getInPoint:async()=>tick(row.in),getOutPoint:async()=>tick(row.out),getDuration:async()=>tick(row.duration),
            isDisabled:async()=>mode==="disabled",isAdjustmentLayer:async()=>false,isSpeedReversed:async()=>0};
    });
    return {name:["Base","Overlay","Reserved"][index],getTrackItems:type=>type===1?(mode==="oversized-track"?Array(129).fill(clips[0]):clips):[],getIndex:async()=>index,isMuted:async()=>mode==="muted"};
});
const sequence={guid:guid("sequence-guid"),name:variant?"Schemaxis Layout Variant":"Schemaxis Layout",getFrameSize:async()=>({width:32,height:24}),getVideoTrackCount:async()=>tracks.length,getAudioTrackCount:async()=>0,getCaptionTrackCount:async()=>0,getVideoTrack:async index=>{snapshots++;return tracks[index];},
    getTimebase:async()=>"10160640000",getZeroPoint:async()=>tick("0"),getEndTime:async()=>tick(mode==="changed-sequence" && snapshots>3?"111767040000":"101606400000")};
const project={guid:guid("project-guid"),name:"colours",path:"/replace-with-your-project/colours.prproj",getActiveSequence:async()=>sequence};
const ppro={Project:{getActiveProject:async()=>project},ClipProjectItem:{cast:value=>value}};
const uxp={host:{name:"premierepro",version:"26.5.0",applicationPath:"/Applications/Adobe Premiere Pro/Adobe Premiere Pro.app"},versions:{uxp:"uxp-9.3.0-local"}};
if(mode==="stale-response") {const request=JSON.parse(fs.readFileSync(path.join(directory,"request.json")));fs.writeFileSync(path.join(directory,request.responseFile),"prior response");}
observer.observeFolder(folder,ppro,uxp).then(response=>process.stdout.write(JSON.stringify(response))).catch(error=>{process.stderr.write(error.message);process.exitCode=1;});
