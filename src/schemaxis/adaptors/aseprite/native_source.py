# Copyright (C) 2026 David L F Gaden
"""Trusted Lua source shipped as Python package data without packaging hooks."""

# Previous packaged procedural-only worker: retained evidence without a capture
# manifest may use exactly this trusted source identity, never arbitrary Lua.
LEGACY_PROCEDURAL_WORKER_SHA256 = '09bcdb34c346d95d1803a2dbadc4ddd0445b756f5393f4a95e8eb26287610099'

WORKER = r'''
-- Trusted worker. Authored JSON is data, never Lua source or reflected API names.
local function read(path)
  local f = assert(io.open(path, "rb"))
  local text = f:read("*a"); f:close()
  return json.decode(text)
end
local function write(path, value)
  local f = assert(io.open(path, "wb"))
  f:write(json.encode(value)); f:close()
end
local dirs = {forward=AniDir.FORWARD, reverse=AniDir.REVERSE,
              pingPong=AniDir.PING_PONG, pingPongReverse=AniDir.PING_PONG_REVERSE}
local function colour(c) return Color{r=c[1], g=c[2], b=c[3], a=c[4]} end
local function palette(sprite, colours)
  local p = Palette(#colours)
  for i,c in ipairs(colours) do p:setColor(i-1, colour(c)) end
  sprite:setPalette(p)
end
local function tags(sprite)
  local out = {}
  for _,t in ipairs(sprite.tags) do
    local direction
    for k,v in pairs(dirs) do if t.aniDir == v then direction = k end end
    out[#out+1] = {name=t.name, fromFrame=t.fromFrame.frameNumber, toFrame=t.toFrame.frameNumber, direction=direction}
  end
  table.sort(out, function(a,b) return a.name < b.name end)
  return out
end
local function metadata(sprite)
  local out = {version="schemaxis.aseprite.sheet/1", width=sprite.width*#sprite.frames,
               height=sprite.height, frames={}, tags=tags(sprite)}
  for i,f in ipairs(sprite.frames) do
    out.frames[i] = {x=(i-1)*sprite.width, y=0, width=sprite.width, height=sprite.height,
                     durationMS=math.floor(f.duration*1000+0.5)}
  end
  return out
end
local function hexPixel(p)
  local pc = app.pixelColor
  if pc.rgbaA(p) == 0 then return "00000000" end
  return string.format("%02x%02x%02x%02x", pc.rgbaR(p), pc.rgbaG(p), pc.rgbaB(p), pc.rgbaA(p))
end
local function imageData(image)
  assert(image.colorMode == ColorMode.RGB, "expected RGB image")
  local data = {}
  for y=0,image.height-1 do
    for x=0,image.width-1 do data[#data+1] = hexPixel(image:getPixel(x,y)) end
  end
  return {width=image.width, height=image.height, pixels=table.concat(data)}
end
local function snapshot(sprite)
  assert(sprite.colorMode == ColorMode.RGB, "expected RGB sprite")
  local out = {width=sprite.width, height=sprite.height, colourMode="RGB", layers={},
               durationsMS={}, palette={}, tags=tags(sprite), cels={}}
  for i,f in ipairs(sprite.frames) do out.durationsMS[i] = math.floor(f.duration*1000+0.5) end
  local p = sprite.palettes[1]
  for i=0,#p-1 do
    local c = p:getColor(i)
    out.palette[i+1] = {c.red, c.green, c.blue, c.alpha}
  end
  for i,layer in ipairs(sprite.layers) do
    assert(layer.isImage and layer.isVisible and layer.opacity == 255 and layer.blendMode == BlendMode.NORMAL)
    out.layers[i] = layer.name; out.cels[i] = {}
    for f=1,#sprite.frames do
      local cel = layer:cel(f)
      local data = {}
      for y=0,sprite.height-1 do
        for x=0,sprite.width-1 do
          local pixel = 0
          if cel then
            assert(cel.opacity == 255)
            local cx,cy = x-cel.position.x,y-cel.position.y
            if cx >= 0 and cy >= 0 and cx < cel.image.width and cy < cel.image.height then
              pixel = cel.image:getPixel(cx,cy)
            end
          end
          data[#data+1] = hexPixel(pixel)
        end
      end
      out.cels[i][f] = table.concat(data)
    end
  end
  return out
end
if app.params.stage == "build" then
  local plan = read("plan.json")
  local sprite
  local layers = {}
  local imported = {}
  for _,record in ipairs(read("input-manifest.json").images) do imported[record.node] = record end
  for _,node in ipairs(plan.nodes) do
    local op,o = node.filter,node.options
    if op == "sprite" then
      sprite = Sprite(o.width,o.height,ColorMode.RGB)
      sprite.layers[1].name = o.layer; layers[o.layer] = sprite.layers[1]
      sprite.frames[1].duration = o.durationMS/1000
      palette(sprite,o.colours)
    elseif op == "layer" then
      local l = sprite:newLayer(); l.name = o.name; layers[o.name] = l
    elseif op == "frame" then
      local f = sprite:newEmptyFrame(#sprite.frames+1); f.duration = o.durationMS/1000
    elseif op == "palette" then palette(sprite,o.colours)
    elseif op == "tag" then
      local t = sprite:newTag(o.fromFrame,o.toFrame); t.name = o.name; t.aniDir = dirs[o.direction]
    elseif op == "importImage" then
      local record = assert(imported[node.id], "missing captured image")
      local source = Image{fromFile=record.retained}
      assert(source.colorMode == ColorMode.RGB and source.width == o.width and source.height == o.height)
      local l = assert(layers[o.layer])
      local cel = l:cel(o.frame)
      local image = Image(sprite.width,sprite.height,ColorMode.RGB)
      -- Normalise a trimmed cel back to canvas coordinates before replacement.
      if cel then image:drawImage(cel.image,cel.position) end
      for y=0,o.height-1 do
        for x=0,o.width-1 do
          local pixel = source:getPixel(x,y)
          local alpha = app.pixelColor.rgbaA(pixel)
          assert(alpha == 0 or alpha == 255, "partial alpha is unsupported")
          image:drawPixel(o.x+x,o.y+y,alpha == 0 and 0 or pixel)
        end
      end
      if cel then cel.image = image; cel.position = Point(0,0)
      else sprite:newCel(l,o.frame,image,Point(0,0)) end
    elseif op == "pixel" or op == "rect" or op == "circle" then
      local l = assert(layers[o.layer])
      local cel = l:cel(o.frame)
      local image = Image(sprite.width,sprite.height,ColorMode.RGB)
      if cel then image:drawImage(cel.image,cel.position) end
      local c = app.pixelColor.rgba(o.colour[1],o.colour[2],o.colour[3],o.colour[4])
      if op == "circle" then
        for dy=-o.radius,o.radius do
          for dx=-o.radius,o.radius do
            if dx*dx+dy*dy <= o.radius*o.radius then image:drawPixel(o.x+dx,o.y+dy,c) end
          end
        end
      else
        for y=o.y,o.y+(o.height or 1)-1 do
          for x=o.x,o.x+(o.width or 1)-1 do image:drawPixel(x,y,c) end
        end
      end
      if cel then cel.image = image; cel.position = Point(0,0) else sprite:newCel(l,o.frame,image,Point(0,0)) end
    else error("unsupported operation") end
  end
  sprite:saveAs("sprite.aseprite")
  local preview = Image(sprite.width,sprite.height,ColorMode.RGB)
  preview:drawSprite(sprite,1); preview:saveAs("preview.png")
  local sheet = Image(sprite.width*#sprite.frames,sprite.height,ColorMode.RGB)
  for i=1,#sprite.frames do sheet:drawSprite(sprite,i,Point((i-1)*sprite.width,0)) end
  sheet:saveAs("sheet.png")
  write("sheet.json",metadata(sprite))
elseif app.params.stage == "reopen" then
  local sprite = assert(app.open("sprite.aseprite"))
  write("verification.json", {freshProcess=true, runtime=tostring(app.version), native=snapshot(sprite),
    preview=imageData(Image{fromFile="preview.png"}), sheet=imageData(Image{fromFile="sheet.png"})})
else error("unsupported worker stage") end
'''
