# LeVision

LeVision is a real-time sports analytics system that detects players from video, tracks their movement, identifies jersey numbers, and overlays live player statistics directly onto game footage.

Our goal is to make sports broadcasts more interactive by automatically linking visual player data with real-time performance insights.

## Current Focus

- Offline video processing (recorded games)
- Player detection and multi-object tracking
- Jersey number recognition (OCR)
- Player stat retrieval and overlay rendering

---

## Local Dev Setup

### Web App (`levision-web/`)

The web app is a Next.js project connected to Supabase for auth and data.

#### 1. Install dependencies

```bash
cd levision-web
npm install
```

#### 2. Set up environment variables

Create `levision-web/.env.local`:

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key
```

Get these from your Supabase project → Settings → API.

#### 3. Run the dev server

```bash
npm run dev
```

App runs at `http://localhost:3000`.

---

### Python / Backend

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
| --- | --- |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (never expose publicly) |
| `ESPN_SUMMARY_URL` | ESPN game summary API endpoint |
| `SCHEMA_MODE` | `snake` for snake_case column mapping |
| `DRY_RUN` | `true` to skip writes during testing |

### Vision Pipeline (`vision/`)

Requires a `ROBOFLOW_API_KEY` (free on roboflow) environment variable:

```bash
export ROBOFLOW_API_KEY=your-key

With a GPU (full pipeline including SAM2 tracking):

python vision/fresh_vision_pipeline.py \
  --source-video-directory path/to/videos \
  --source-video-name your_game.mp4

Without a GPU (skips SAM2, still runs detection, OCR, and court mapping):

python vision/fresh_vision_pipeline.py \
  --source-video-directory path/to/videos \
  --source-video-name your_game.mp4 \
  --skip-sam2

Outputs are saved to fresh_vision_outputs/ by default. Use --output-directory to change this.

To do a check without processing the full video:

python vision/vision_pipeline.py \
  --source-video-directory path/to/videos \
  --source-video-name game.mp4 \
  --mode smoke \
  --skip-sam2
