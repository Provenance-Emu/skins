import {test} from 'node:test';
import assert from 'node:assert/strict';
import {layouts,config,parseInfo} from '../../docs/js/retroarch-core.mjs';
const data={mappingSize:{width:400,height:800},items:[{frame:{x:100,y:200,width:80,height:40},inputs:['a','b']},{frame:{x:0,y:0,width:40,height:40},inputs:['touchScreenX']}]};
test('exports device-specific iPhone, iPad and TV layouts',()=>{
 const info={representations:{iphone:{edgeToEdge:{portrait:data}},ipad:{standard:{landscape:data}},tv:{standard:{landscape:data}}}};
 assert.deepEqual(layouts(info).map(l=>l.device),['iphone','ipad','tv']);
});
test('normalizes hitboxes, preserves combos, omits unsupported input with contiguous descriptors',()=>{
 const warnings=new Set(), cfg=config({data},warnings);
 assert.match(cfg,/overlay0_descs = 1/);
 assert.match(cfg,/a\|b,0.35,0.275,rect,0.1,0.025/);
 assert.equal(warnings.size,1);
 assert.doesNotMatch(cfg,/touchScreenX/);
});
test('reads comments and trailing commas without corrupting strings',()=>{
 assert.deepEqual(parseInfo('{"url":"https://example.com/x,}", // comment\n "a":[1,],}'),{url:'https://example.com/x,}',a:[1]});
});
