declare global {
  interface ImportMetaEnv {
    readonly MODE: 'development' | 'production' | 'test'
    readonly DEV: boolean
  }

  interface ImportMeta {
    readonly env: ImportMetaEnv
  }
}

export {}
