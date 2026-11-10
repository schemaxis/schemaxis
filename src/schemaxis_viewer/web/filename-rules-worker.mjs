// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {extractFilenameProperties} from './filename-rules.mjs';
self.onmessage=({data})=>{
  try{self.postMessage(extractFilenameProperties(data.records,data.rules));}
  catch(error){self.postMessage({error:error.message});}
};
