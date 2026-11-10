// Copyright (C) 2026 David L. F. Gaden. SPDX-License-Identifier: Apache-2.0
import {searchLines} from './search.mjs';
self.onmessage=({data})=>{
  try {self.postMessage(searchLines(data));}
  catch(error){self.postMessage({error:error.message});}
};
