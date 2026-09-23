/**
 * Chrome80 运行时 API 补齐（浙警智治上架要求：支持 Chrome 内核浏览器，基线 Chrome80）
 *
 * 为什么需要：
 * - `?.` / `??` 是 Chrome80 自带特性，构建期无需降级（见 scripts/check-es-target.cjs）；
 * - 但依赖里出现了 **Chrome80 不存在的运行时 API**（Element Plus 的 `arr.at(-1)`、
 *   Pinia 的 `Object.hasOwn`），这类不是语法问题，构建期降级解决不了，必须在运行时补。
 *
 * 本文件必须在 main.ts **最前面**导入（早于任何依赖模块执行）。
 * 已存在实现时直接跳过（新浏览器不受影响）。
 */

/* eslint-disable @typescript-eslint/no-explicit-any */
const anyArray = Array.prototype as any
const anyObject = Object as any

if (typeof anyArray.at !== 'function') {
  // Array.prototype.at（Chrome 92 才原生支持）
  Object.defineProperty(anyArray, 'at', {
    value: function at(this: unknown[], index: number) {
      const len = this.length >>> 0
      let i = Math.trunc(index) || 0
      if (i < 0) i += len
      return i < 0 || i >= len ? undefined : this[i]
    },
    writable: true,
    configurable: true,
  })
}

if (typeof (String.prototype as any).at !== 'function') {
  Object.defineProperty(String.prototype, 'at', {
    value: function at(this: string, index: number) {
      const len = this.length
      let i = Math.trunc(index) || 0
      if (i < 0) i += len
      return i < 0 || i >= len ? undefined : this.charAt(i)
    },
    writable: true,
    configurable: true,
  })
}

if (typeof anyObject.hasOwn !== 'function') {
  // Object.hasOwn（Chrome 93 才原生支持）
  Object.defineProperty(Object, 'hasOwn', {
    value: (obj: unknown, key: PropertyKey) =>
      Object.prototype.hasOwnProperty.call(obj, key),
    writable: true,
    configurable: true,
  })
}

export {}
