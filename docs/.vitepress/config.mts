import { defineConfig } from "vitepress"

export default defineConfig({
  lang: "zh-CN",
  title: "BidirectionalCommunication",
  description: "基于 FastAPI 和 WebSocket 的双向通信学习项目",
  base: "/BidirectionalCommunication/",
  cleanUrls: true,
  lastUpdated: true,

  head: [["meta", { name: "theme-color", content: "#3451b2" }]],

  themeConfig: {
    siteTitle: "BidirectionalCommunication",
    nav: [
      { text: "首页", link: "/" },
      { text: "快速开始", link: "/guide/getting-started" },
      { text: "消息协议", link: "/guide/message-protocol" },
      { text: "架构", link: "/guide/architecture" },
      { text: "数据库", link: "/guide/database-foundations" },
      { text: "领域模型", link: "/domain/message-model" },
      {
        text: "GitHub",
        link: "https://github.com/NayukiChiba/BidirectionalCommunication",
      },
    ],

    sidebar: [
      {
        text: "项目指南",
        items: [
          { text: "快速开始", link: "/guide/getting-started" },
          { text: "WebSocket 消息协议", link: "/guide/message-protocol" },
          { text: "架构与组合根", link: "/guide/architecture" },
          { text: "关系建模与 SQLAlchemy", link: "/guide/database-foundations" },
        ],
      },
      {
        text: "架构设计",
        items: [
          { text: "消息领域模型", link: "/domain/message-model" },
        ],
      },
    ],

    search: {
      provider: "local",
    },

    outline: {
      level: [2, 3],
      label: "本页目录",
    },

    docFooter: {
      prev: "上一页",
      next: "下一页",
    },

    lastUpdated: {
      text: "最后更新于",
      formatOptions: {
        dateStyle: "medium",
        timeStyle: "short",
      },
    },

    socialLinks: [
      {
        icon: "github",
        link: "https://github.com/NayukiChiba/BidirectionalCommunication",
      },
    ],

    footer: {
      message: "以可学习、可解释、可逐步验收为目标",
      copyright: "BidirectionalCommunication",
    },
  },
})
