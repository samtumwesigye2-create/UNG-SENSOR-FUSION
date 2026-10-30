import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router'
import { MacalyBridge } from '@macaly/bridge'

// CSS imported as a side effect — do NOT add `?url` or `?inline`.
//
// Why: TanStack Start runs two Vite build environments (client + ssr) with
// independent module graphs. A `?url` import resolves the CSS URL twice and
// the two passes can produce different hashes; the SSR pass bakes its hash
// into the prerendered HTML, but only the client's asset actually exists in
// `dist/client/assets/`, so the stylesheet 404s and the page loads unstyled.
//
// A bare side-effect import sidesteps the issue: only the client environment
// emits the CSS asset, and TanStack Start's manifest collection injects the
// correct hashed `<link rel="stylesheet">` into the rendered head from the
// client manifest. The CSS stays a shared, cacheable asset (important if
// prerender is expanded to multiple static pages — `?inline` would duplicate
// the CSS into every HTML file).
import '../styles.css'
import siteMetadata from '../metadata.json'

const rootMeta = siteMetadata['/']

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: rootMeta.title },
      { name: 'description', content: rootMeta.description },
    ],
    links: [
      { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
      { rel: 'manifest', href: '/manifest.json' },
    ],
  }),
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <HeadContent />
      </head>
      <MacalyBridge>
        <body>
          {children}
          <Scripts />
        </body>
      </MacalyBridge>
    </html>
  )
}
