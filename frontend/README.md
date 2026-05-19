# APEX Frontend

Next.js 14 (App Router) + TypeScript + Tailwind + shadcn-style components.
Wired to the live backend at `https://apex-api-production-3b77.up.railway.app`.

## Develop

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
# → http://localhost:3000
```

The dev server proxies nothing; the browser talks to the API directly using
`NEXT_PUBLIC_API_URL` and a JWT held in `localStorage`.

## Scripts

| Command            | Description                          |
| ------------------ | ------------------------------------ |
| `npm run dev`      | Next.js dev server                   |
| `npm run build`    | Production build                     |
| `npm run start`    | Run the built app                    |
| `npm run lint`     | `next lint` (ESLint, Next core rules)|
| `npm run typecheck`| `tsc --noEmit` with `strict: true`   |

## Routes

- `/login` — public
- `/dashboard` — rep dashboard
- `/pipeline` — kanban (dnd-kit)
- `/contacts`, `/contacts/[id]`
- `/inbox` — threads with status + SLA + AI draft pills
- `/companies`, `/calls`, `/reports`, `/sequences`, `/workflows`, `/settings` — shell + empty states (placeholders)

Authenticated routes are gated by `src/middleware.ts`, which checks for an
`apex_token` cookie that is mirrored from `localStorage` on login.

## Design tokens

Defined in `tailwind.config.ts`:

- Primary `#1F4E79`, Accent `#2E75B6`, AI `#7C3AED`
- Success `#16A34A`, Warning `#D97706`, Danger `#DC2626`
- Background `#F8FAFC`, Surface `#FFFFFF`, Border `#E2E8F0`
- Font: Inter (via `next/font`)
