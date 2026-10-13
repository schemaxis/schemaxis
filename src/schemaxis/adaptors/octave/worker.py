"""Fixed Octave program; authored documents never contain executable source."""
WORKER = r'''1; % Explicit script containing local functions.
function emit_json(path, value)
  fid = fopen(path, "w");
  if fid < 0, error("cannot open output"); endif
  unwind_protect
    fputs(fid, jsonencode(value));
  unwind_protect_cleanup
    fclose(fid);
  end_unwind_protect
endfunction
function summary = describe_values(y)
  summary = struct("count",numel(y), "mean",mean(y), "median",median(y),
    "stdSample",std(y,0), "minimum",min(y), "maximum",max(y), "rms",sqrt(mean(y.^2)));
endfunction
request = jsondecode(fileread("request.json"));
plan = request.plan;
records = struct();
for index = 1:numel(plan.nodes)
  node = plan.nodes(index); o = node.options; op = node.filter;
  metadata = struct();
  switch op
    case "samples"
      x = o.x(:); y = o.y(:);
    case "readCSV"
      source = request.sources.(node.id);
      xi = find(strcmp(source.columns,o.xColumn));
      yi = find(strcmp(source.columns,o.yColumn));
      x = source.rows(:,xi); y = source.rows(:,yi);
    case "sequence"
      x = linspace(o.start,o.stop,o.count)'; y = x;
    case "wave"
      x = o.start + o.step*(0:o.count-1)';
      phase = 2*pi*o.frequency*x + o.phase;
      if strcmp(o.shape,"sine"), y = sin(phase); else y = cos(phase); endif
      y = o.offset + o.amplitude*y;
    otherwise
      source = records.(node.inputs.input); x = source.x(:); y = source.y(:);
      switch op
        case "scale"
          y = o.factor*y + o.offset;
        case "resample"
          target = linspace(x(1),x(end),o.count)';
          y = interp1(x,y,target,"linear"); x = target;
        case "movingMean"
          y = movmean(y,o.window,"Endpoints","shrink");
        case "derivative"
          y = gradient(y,x);
        case "integral"
          y = o.initial + cumtrapz(x,y);
        case "linearFit"
          p = polyfit(x,y,1); fitted = polyval(p,x);
          metadata = struct("slope",p(1),"intercept",p(2),"residualSumSquares",sum((y-fitted).^2));
          y = fitted;
        case "fft"
          n = numel(x); spacing = (x(end)-x(1))/(n-1);
          spectrum = fft(y); y = abs(spectrum(1:n/2+1))/n;
          y(2:end-1) *= 2;
          x = (0:n/2)'/(n*spacing);
          metadata = struct("sampleSpacing",spacing,"sourceCount",n);
        otherwise
          error("undeclared numerical operation");
      endswitch
  endswitch
  if any(!isfinite(x)) || any(!isfinite(y)), error("nonfinite numerical output"); endif
  records.(node.id) = struct("x",x',"y",y',"metadata",metadata,"statistics",describe_values(y));
endfor
summary = struct();
for index = 1:numel(plan.outputs)
  identity = plan.outputs{index}; record = records.(identity);
  fid = fopen([identity ".csv"],"w");
  if fid < 0, error("cannot open CSV"); endif
  unwind_protect
    fprintf(fid,"x,y\n");
    fprintf(fid,"%.17g,%.17g\n",[record.x(:),record.y(:)]');
  unwind_protect_cleanup
    fclose(fid);
  end_unwind_protect
  summary.(identity) = record.statistics;
endfor
emit_json("statistics.json",summary);
emit_json("native.json",struct("runtime",version,"nodes",records));
'''
