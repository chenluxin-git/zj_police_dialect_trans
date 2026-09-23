// 校验 polyfills 的语义正确性（在"删掉原生实现"的前提下验证补齐逻辑）
// 运行：node scripts/_probe-polyfill.cjs
const savedAt = Array.prototype.at
const savedStringAt = String.prototype.at
const savedHasOwn = Object.hasOwn
delete Array.prototype.at
delete String.prototype.at
delete Object.hasOwn

Object.defineProperty(Array.prototype, 'at', {
  value: function at(index) {
    const len = this.length >>> 0
    let i = Math.trunc(index) || 0
    if (i < 0) i += len
    return i < 0 || i >= len ? undefined : this[i]
  },
  writable: true,
  configurable: true,
})
Object.defineProperty(String.prototype, 'at', {
  value: function at(index) {
    const len = this.length
    let i = Math.trunc(index) || 0
    if (i < 0) i += len
    return i < 0 || i >= len ? undefined : this.charAt(i)
  },
  writable: true,
  configurable: true,
})
Object.defineProperty(Object, 'hasOwn', {
  value: (obj, key) => Object.prototype.hasOwnProperty.call(obj, key),
  writable: true,
  configurable: true,
})

let failed = 0
const assert = (cond, msg) => {
  if (cond) console.log('ok: ' + msg)
  else {
    console.error('FAIL: ' + msg)
    failed++
  }
}

assert([1, 2, 3].at(-1) === 3, '[1,2,3].at(-1) === 3')
assert([1, 2, 3].at(0) === 1, '[1,2,3].at(0) === 1')
assert([1, 2, 3].at(9) === undefined, '[1,2,3].at(9) === undefined')
assert([1, 2, 3].at(-9) === undefined, '[1,2,3].at(-9) === undefined')
assert([].at(-1) === undefined, '[].at(-1) === undefined')
assert('abc'.at(-1) === 'c', "'abc'.at(-1) === 'c'")
assert('abc'.at(5) === undefined, "'abc'.at(5) === undefined")
assert(Object.hasOwn({ a: 1 }, 'a') === true, "Object.hasOwn({a:1},'a') === true")
assert(Object.hasOwn({ a: 1 }, 'b') === false, "Object.hasOwn({a:1},'b') === false")
assert(Object.hasOwn({}, 'toString') === false, 'hasOwn 不认原型链上的属性')
assert(Object.hasOwn([1], 0) === true, 'hasOwn 认数组下标')
assert(Object.hasOwn(new (class A { constructor() { this.x = 1 } })(), 'x') === true, 'hasOwn 认实例属性')

Object.defineProperty(Array.prototype, 'at', { value: savedAt, writable: true, configurable: true })
Object.defineProperty(String.prototype, 'at', { value: savedStringAt, writable: true, configurable: true })
Object.defineProperty(Object, 'hasOwn', { value: savedHasOwn, writable: true, configurable: true })

console.log(failed ? `polyfill 自检失败（${failed} 项）` : 'polyfill 自检通过')
process.exit(failed ? 1 : 0)
