"use strict";
// SHA-256 of ASCII-only trusted request bytes. Host JSON escapes non-ASCII.
// This avoids assuming WebCrypto, BigInt or a Node crypto module exists in UXP.
function sha256(text) {
    if (typeof text !== "string" || text.length > 1048576 || /[^\x00-\x7f]/.test(text)) throw Error("Request bytes must be bounded ASCII JSON");
    const k = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19], words = [];
    for (let i=0;i<text.length;i++) words[i>>2] = (words[i>>2] || 0) | (text.charCodeAt(i) << (24-(i%4)*8));
    words[text.length>>2] = (words[text.length>>2] || 0) | (0x80 << (24-(text.length%4)*8));
    const blocks = Math.ceil((text.length + 9)/64);
    words[blocks*16-1] = text.length*8;
    const r = (x,n) => (x>>>n) | (x<<(32-n));
    for (let offset=0;offset<blocks*16;offset+=16) {
        const w = [];
        for(let i=0;i<64;i++) {
            if(i<16) w[i] = words[offset+i] || 0;
            else { const x=w[i-15],y=w[i-2]; w[i]=((r(x,7)^r(x,18)^(x>>>3))+w[i-16]+(r(y,17)^r(y,19)^(y>>>10))+w[i-7])|0; }
        }
        let [a,b,c,d,e,f,g,j] = h;
        for(let i=0;i<64;i++) {
            const t1=(j+(r(e,6)^r(e,11)^r(e,25))+((e&f)^(~e&g))+k[i]+w[i])|0;
            const t2=((r(a,2)^r(a,13)^r(a,22))+((a&b)^(a&c)^(b&c)))|0;
            j=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;
        }
        [a,b,c,d,e,f,g,j].forEach((v,i)=>{h[i]=(h[i]+v)|0;});
    }
    return h.map(v=>(v>>>0).toString(16).padStart(8,"0")).join("");
}
function closed(value, fields) {
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join("|") !== fields.slice().sort().join("|")) throw Error("Unexpected contract fields");
}
function text(value, limit=4096) {
    if(typeof value !== "string" || !value.length || value.length>limit || value.includes("\0")) throw Error("Missing bounded native identity");
    return value;
}
function ticks(value) { const v=value && value.ticks; if(typeof v!=="string" || !/^(0|[1-9][0-9]{0,18})$/.test(v)) throw Error("Invalid exact native ticks"); return v; }
function integer(value, low, high) { if(!Number.isInteger(value) || value<low || value>high) throw Error("Native count exceeds bound"); return value; }
function boolean(value) { if(typeof value!=="boolean") throw Error("Missing native boolean state"); return value; }
function guid(value) { return text(value && value.toString(),256); }
function request(raw, now) {
    sha256(raw);
    const value = JSON.parse(raw);
    closed(value,["version","operation","nonce","expiresAtMs","responseFile","contract"]);
    if(value.version!=="schemaxis.premiere.request/1" || value.operation!=="sequenceContract" || !/^[0-9a-f]{32}$/.test(value.nonce) || value.responseFile!=="response-"+value.nonce+".json") throw Error("Invalid attempt identity");
    integer(value.expiresAtMs,1,999999999999999);
    if(value.expiresAtMs<=now || value.expiresAtMs>now+3600000) throw Error("Request expired or deadline exceeds one hour");
    closed(value.contract,["version","operation","options","timebaseTicks","endTicks","frames","clips","losses"]);
    if(value.contract.version!=="schemaxis.premiere.plan/1" || value.contract.operation!=="sequenceContract") throw Error("Invalid planned contract");
    integer(value.contract.frames,1,600);
    if(!Array.isArray(value.contract.clips) || value.contract.clips.length<1 || value.contract.clips.length>128) throw Error("Clip contract exceeds bound");
    return value;
}
async function active(ppro) {
    const project=await ppro.Project.getActiveProject();
    if(!project) throw Error("Open a saved Premiere project");
    const sequence=await project.getActiveSequence();
    if(!sequence) throw Error("Activate the sequence to inspect");
    return {project,sequence,identity:{project:guid(project.guid),sequence:guid(sequence.guid)}};
}
async function snapshot(ppro,uxp) {
    const state=await active(ppro), project=state.project, sequence=state.sequence;
    const frame=await sequence.getFrameSize();
    const videoTrackCount=integer(await sequence.getVideoTrackCount(),1,1);
    const audioTrackCount=integer(await sequence.getAudioTrackCount(),0,8);
    const captionTrackCount=integer(await sequence.getCaptionTrackCount(),0,0);
    const track=await sequence.getVideoTrack(0);
    // Public constants are Clip=1 and Transition=2. Include-empty is false.
    const nativeClips=track.getTrackItems(1,false), transitions=track.getTrackItems(2,false);
    if(!Array.isArray(nativeClips) || nativeClips.length<1 || nativeClips.length>128 || !Array.isArray(transitions) || transitions.length>128) throw Error("Native track item count exceeds bound");
    let audioClipCount=0;
    for(let i=0;i<audioTrackCount;i++) {
        const audio=await sequence.getAudioTrack(i), items=audio.getTrackItems(1,false), audioTransitions=audio.getTrackItems(2,false);
        if(!Array.isArray(items) || !Array.isArray(audioTransitions) || items.length>128 || audioTransitions.length>128) throw Error("Native audio count exceeds bound");
        audioClipCount+=items.length+audioTransitions.length;
    }
    const clips=[];
    for(const item of nativeClips) {
        const base=await item.getProjectItem(), source=ppro.ClipProjectItem.cast(base);
        if(!source) throw Error("Video item is not a media clip");
        const reversed=await item.isSpeedReversed();
        if(reversed!==0 && reversed!==1) throw Error("Invalid native reversal flag");
        clips.push({name:text(await item.getName()),projectItemId:text(base.getId()),sourcePath:text(await source.getMediaFilePath()),
            startTicks:ticks(await item.getStartTime()),endTicks:ticks(await item.getEndTime()),
            inTicks:ticks(await item.getInPoint()),outTicks:ticks(await item.getOutPoint()),durationTicks:ticks(await item.getDuration()),
            disabled:boolean(await item.isDisabled()),adjustmentLayer:boolean(await item.isAdjustmentLayer()),reversed:reversed===1,
            offline:boolean(await source.isOffline()),nested:boolean(await source.isSequence()),merged:boolean(await source.isMergedClip()),
            multicam:boolean(await source.isMulticamClip()),proxy:boolean(await source.hasProxy())});
    }
    // Exact decimal comparison without converting ticks to imprecise numbers.
    clips.sort((a,b)=>a.startTicks.length-b.startTicks.length || (a.startTicks<b.startTicks?-1:a.startTicks>b.startTicks?1:0));
    const observed={runtime:{hostName:text(uxp.host.name),hostVersion:text(uxp.host.version),uxpVersion:text(uxp.versions.uxp),applicationPath:text(uxp.host.applicationPath)},
        project:{name:text(project.name),path:text(project.path),guid:state.identity.project},
        sequence:{name:text(sequence.name),guid:state.identity.sequence,width:integer(frame.width,2,8192),height:integer(frame.height,2,8192),
            timebaseTicks:text(await sequence.getTimebase(),19),zeroPointTicks:ticks(await sequence.getZeroPoint()),endTicks:ticks(await sequence.getEndTime()),
            videoTrackCount,audioTrackCount,captionTrackCount},
        track:{index:integer(await track.getIndex(),0,0),name:text(track.name,256),muted:boolean(await track.isMuted()),audioClipCount,transitionCount:transitions.length},clips};
    if(JSON.stringify((await active(ppro)).identity)!==JSON.stringify(state.identity)) throw Error("Active project or sequence changed during observation");
    return observed;
}
async function observeFolder(folder,ppro,uxp) {
    const entries=await folder.getEntries();
    const requests=entries.filter(entry=>entry.name==="request.json" && entry.isFile);
    if(requests.length!==1) throw Error("Select the fresh Schemaxis job folder containing request.json");
    const file=requests[0],raw=await file.read(),job=request(raw,Date.now()),digest=sha256(raw);
    if(entries.some(entry=>entry.name===job.responseFile)) throw Error("This attempt already has a response; use a fresh job");
    const first=await snapshot(ppro,uxp),second=await snapshot(ppro,uxp);
    if(JSON.stringify(first)!==JSON.stringify(second)) throw Error("Sequence changed between observations; retry while idle");
    // Re-read the request immediately before writing; stale jobs cannot borrow
    // an observation gathered for an earlier authored contract or nonce.
    const fresh=await file.read();
    request(fresh,Date.now());
    if(sha256(fresh)!==digest) throw Error("Request changed during observation");
    const response={version:"schemaxis.premiere.response/1",nonce:job.nonce,requestSHA256:digest,status:"observed",observation:second};
    // ASCII escaping makes this character bound also the exact UTF-8 byte
    // bound, including native Unicode paths/names and surrogate pairs.
    const encoded=(JSON.stringify(response,null,2)+"\n").replace(/[^\x00-\x7f]/g,
        character=>"\\u"+character.charCodeAt(0).toString(16).padStart(4,"0"));
    if(encoded.length>1048576) throw Error("Native observation byte bound exceeded");
    const output=await folder.createFile("pending-"+job.nonce+".json",{overwrite:false});
    await output.write(encoded);
    const beforePublish=await file.read();
    request(beforePublish,Date.now());
    if(sha256(beforePublish)!==digest) throw Error("Request changed before publication");
    // Publish only after write completion. The host never reads a half-written
    // response name. moveTo is the documented UXP storage Entry operation.
    await output.moveTo(folder,{newName:job.responseFile,overwrite:false});
    return response;
}
module.exports={sha256,request,snapshot,observeFolder};
