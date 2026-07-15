import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Article, StyleType } from '@/types'
import { generateArticle, fetchArticles } from '@/api'

export const useArticleStore = defineStore('article', () => {
  const articles = ref<Article[]>([])

  async function createArticle(
    newsIds: string[],
    style: StyleType,
    title?: string
  ): Promise<Article | null> {
    if (newsIds.length === 0) return null
    const article = await generateArticle(newsIds, style, title)
    articles.value.push(article)
    return article
  }

  async function loadArticles() {
    articles.value = await fetchArticles()
  }

  /** 直接追加一个已构造好的文章对象（例如流式生成完成后） */
  function addArticle(article: Article) {
    articles.value.push(article)
  }

  return {
    articles,
    createArticle,
    loadArticles,
    addArticle,
  }
})
