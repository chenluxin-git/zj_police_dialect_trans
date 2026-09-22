/**
 * 标注 API（对应后端 P-annotate T10 /api/annotations）
 * - next：领取一条音频（180s 锁）；无货 404 + code=1 拦截器报错
 * - 音频流 file_url = /api/audio/files/{file_id}/file；播放用 fetchAudioBlob 带 token 转 Blob
 */
import { api } from "./http"

export interface NextAudio {
  file_id: number
  file_name: string
  file_url: string
  region_code: string
  dialect_code: string
}

export interface AnnotationItem {
  id: number
  file_id: number
  file_name: string
  translation: string
  region_code: string
  created_at: string
}

export interface AnnotationPage {
  total: number
  page: number
  page_size: number
  items: AnnotationItem[]
}

export interface AnnotationPayload {
  file_id: number
  translation: string
}

export function nextAudio() {
  return api.get<NextAudio>("/annotations/next")
}

export function submitAnnotation(payload: AnnotationPayload) {
  return api.post<AnnotationItem>("/annotations", payload)
}

export function myAnnotations(params: { page?: number; page_size?: number } = {}) {
  return api.get<AnnotationPage>("/annotations/my", { params })
}

export function updateAnnotation(id: number, payload: AnnotationPayload) {
  return api.put<{ msg: string }>(`/annotations/${id}`, payload)
}

export function deleteAnnotation(id: number) {
  return api.delete<{ msg: string }>(`/annotations/${id}`)
}

export function refreshAnnotationAssignment(fileId: number) {
  return api.post<{ msg: string }>(`/annotations/assign/${fileId}/refresh`)
}

/** 标注音频流 URL（我的标注列表无 file_url，需由 file_id 构造） */
export function audioFileUrl(fileId: number) {
  return `/api/audio/files/${fileId}/file`
}

/** 带 token 拉取音频 Blob（AudioPlayer 播放用） */
export function fetchAudioBlob(url: string) {
  return api.get<Blob>(url.replace(/^\/api/, ""), { responseType: "blob" })
}
