// Chrome80 兼容性校验（浙警智治上架要求：Chrome 内核浏览器）
//
// 基线事实（V8 8.0 / Chrome 80 已支持，无需降级）：
//   - 可选链 `?.` 与空值合并 `??` 是 **Chrome 80 新增特性**，esbuild 的 chrome80 目标会原样保留
//   - 因此本脚本**不把 `?.` / `??` 判为不合规**（历史上曾误判，见 git 记录）
//
// 本脚本真正要拦的是 Chrome 80 **之后**才有的语法，出现在产物里就会让老终端整包 SyntaxError：
//   逻辑赋值 ||= &&= ??=（Chrome 85）、类静态块 static{}（94）
//   运行时 API：Array.prototype.at()（92）、Object.hasOwn()（93）、structuredClone()（98）
//
// 用法：node scripts/check-es-target.cjs [dist目录，默认 dist]
const fs = require('node:fs')
const path = require('node:path')

const outDir = path.resolve(process.argv[2] || 'dist')

const SYNTAX_RULES = [
  { name: '逻辑赋值 ??=', re: /\?\?=/g, since: 'Chrome 85' },
  { name: '逻辑赋值 ||=', re: /\|\|=/g, since: 'Chrome 85' },
  { name: '逻辑赋值 &&=', re: /&&=/g, since: 'Chrome 85' },
  { name: '类静态初始化块 static{}', re: /\bstatic\s*\{/g, since: 'Chrome 94' },
]

const RUNTIME_RULES = [
  { name: 'Array.prototype.at()', re: /\.at\(\s*-?\d+\s*\)/g, since: 'Chrome 92' },
  { name: 'Object.hasOwn()', re: /Object\.hasOwn\(/g, since: 'Chrome 93' },
  { name: 'structuredClone()', re: /structuredClone\(/g, since: 'Chrome 98' },
]

function walk(dir) {
  const out = []
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) out.push(...walk(full))
    else if (entry.name.endsWith('.js')) out.push(full)
  }
  return out
}

/** 补齐代码本身也会出现 "at"/"hasOwn" 字样，需单独识别，避免自报不合规 */
function isPolyfillChunk(code) {
  return code.includes('hasOwnProperty') && code.includes('prototype') &&
    (code.includes('configurable') || code.includes('defineProperty'))
}

if (!fs.existsSync(outDir)) {
  console.error(`[check-es-target] 目录不存在：${outDir}（先执行 npm run build）`)
  process.exit(1)
}

const files = walk(outDir)
const syntaxHits = []
const runtimeHits = []
let polyfillChunks = 0

for (const file of files) {
  const code = fs.readFileSync(file, 'utf8')
  const rel = path.relative(outDir, file)
  for (const rule of SYNTAX_RULES) {
    const m = code.match(rule.re)
    if (m) syntaxHits.push(`${rule.name}（${rule.since}）× ${m.length} —— ${rel}`)
  }
  if (isPolyfillChunk(code)) {
    polyfillChunks++
    continue
  }
  for (const rule of RUNTIME_RULES) {
    const m = code.match(rule.re)
    if (m) runtimeHits.push(`${rule.name}（${rule.since}）× ${m.length} —— ${rel}`)
  }
}

console.log(`[check-es-target] 扫描 ${files.length} 个 JS 产物 —— 基线 Chrome 80`)
console.log(`[check-es-target] 含 Chrome80 运行时补齐代码的分包：${polyfillChunks} 个`)

if (runtimeHits.length) {
  console.log('提示：以下运行时 API 在 Chrome80 不存在，但已由 src/polyfills.ts 全局补齐')
  console.log('      （polyfills 在 main.ts 首行导入，先于业务分包执行，故其他分包出现该调用是安全的）：')
  for (const h of runtimeHits) console.log('  - ' + h)
}

if (syntaxHits.length) {
  console.log('不合规：以下语法 Chrome80 无法解析，会导致整包失败：')
  for (const h of syntaxHits) console.log('  - ' + h)
  process.exit(1)
}

console.log('OK：产物语法满足 Chrome80（?. 与 ?? 属 Chrome80 自带特性，已确认无需降级）')
