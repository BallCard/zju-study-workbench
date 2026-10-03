import test from 'node:test';
import assert from 'node:assert/strict';
import {layoutGraph} from '../web/graph.ts';

test('merge edges preserve both parents and stable branch columns',()=>{
  const rows=[{sha:'merge',parents:['a','b']},{sha:'a',parents:['root']},{sha:'b',parents:['root']},{sha:'root',parents:[]}].map(c=>({...c,date:'',subject:''}));
  const graph=layoutGraph(rows);
  assert.equal(graph.edges.length,4);
  assert.equal(graph.nodes.find(n=>n.sha==='b').lane,1);
  assert.equal(graph.edges.filter(e=>e.from.sha==='merge').length,2);
});
test('history window omits parents outside the window without making fake nodes',()=>{
  const result=layoutGraph([{sha:'head',parents:['outside'],date:'',subject:''}]);
  assert.equal(result.nodes.length,1);assert.equal(result.edges.length,0);
});
