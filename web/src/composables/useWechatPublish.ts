import { ref, reactive } from 'vue'

export interface ImagePublishOptions {
  generate_cover: boolean
  generate_inline_images: boolean
}

export function useWechatPublish() {
  const imageOptsVisible = ref(false)
  const imageOpts = reactive<ImagePublishOptions>({
    generate_cover: true,
    generate_inline_images: false,
  })
  let _resolve: ((opts: ImagePublishOptions | null) => void) | null = null

  function needImageOptions(): Promise<ImagePublishOptions | null> {
    imageOpts.generate_cover = true
    imageOpts.generate_inline_images = false
    imageOptsVisible.value = true
    return new Promise((resolve) => { _resolve = resolve })
  }

  function confirmPublish() {
    imageOptsVisible.value = false
    _resolve?.({ generate_cover: imageOpts.generate_cover, generate_inline_images: imageOpts.generate_inline_images })
    _resolve = null
  }

  function cancelPublish() {
    imageOptsVisible.value = false
    _resolve?.(null)
    _resolve = null
  }

  return { imageOptsVisible, imageOpts, needImageOptions, confirmPublish, cancelPublish }
}
