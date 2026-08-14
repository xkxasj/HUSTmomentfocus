import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'cn.mouke.campus',
  appName: '某刻校园',
  webDir: 'dist',
  android: {
    allowMixedContent: true,
  },
}

export default config
