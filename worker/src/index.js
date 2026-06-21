// CORS headers — allow all origins (prototype)
const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-API-Secret',
};

// Auth check: protected routes require X-API-Secret header
function isAuthorized(request, env) {
  const secret = request.headers.get('X-API-Secret');
  return secret === env.CLOUDFLARE_API_SECRET;
}

// JSON response helper
function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  });
}

export default {
  async fetch(request, env) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders });
    }

    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    try {
      // === PUBLIC ROUTES (no auth) ===

      // GET /api/youtube — list youtube content (paginated)
      if (method === 'GET' && path === '/api/youtube') {
        const page = parseInt(url.searchParams.get('page') || '1');
        const limit = parseInt(url.searchParams.get('limit') || '20');
        const filter = url.searchParams.get('filter'); // friendly, partial, not_friendly
        const offset = (page - 1) * limit;

        let query = 'SELECT * FROM youtube_content WHERE status = ?';
        let params = ['graded'];
        if (filter) {
          query += ' AND grade_animal_friendly = ?';
          params.push(filter);
        }
        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?';
        params.push(limit, offset);

        const { results } = await env.DB.prepare(query).bind(...params).all();
        const { results: countResult } = await env.DB.prepare(
          'SELECT COUNT(*) as total FROM youtube_content WHERE status = ?'
        ).bind('graded').all();

        return jsonResponse({ data: results, total: countResult[0].total, page, limit });
      }

      // GET /api/instagram — list instagram content (paginated)
      if (method === 'GET' && path === '/api/instagram') {
        const page = parseInt(url.searchParams.get('page') || '1');
        const limit = parseInt(url.searchParams.get('limit') || '20');
        const filter = url.searchParams.get('filter');
        const offset = (page - 1) * limit;

        let query = 'SELECT * FROM instagram_content WHERE status = ?';
        let params = ['graded'];
        if (filter) {
          query += ' AND grade_animal_friendly = ?';
          params.push(filter);
        }
        query += ' ORDER BY created_at DESC LIMIT ? OFFSET ?';
        params.push(limit, offset);

        const { results } = await env.DB.prepare(query).bind(...params).all();
        const { results: countResult } = await env.DB.prepare(
          'SELECT COUNT(*) as total FROM instagram_content WHERE status = ?'
        ).bind('graded').all();

        return jsonResponse({ data: results, total: countResult[0].total, page, limit });
      }

      // GET /api/stats — public stats
      if (method === 'GET' && path === '/api/stats') {
        const ytCount = await env.DB.prepare('SELECT COUNT(*) as c FROM youtube_content WHERE status = ?').bind('graded').first();
        const igCount = await env.DB.prepare('SELECT COUNT(*) as c FROM instagram_content WHERE status = ?').bind('graded').first();
        const ytFriendly = await env.DB.prepare("SELECT COUNT(*) as c FROM youtube_content WHERE grade_animal_friendly = 'friendly'").first();
        const ytPartial = await env.DB.prepare("SELECT COUNT(*) as c FROM youtube_content WHERE grade_animal_friendly = 'partial'").first();
        const ytNotFriendly = await env.DB.prepare("SELECT COUNT(*) as c FROM youtube_content WHERE grade_animal_friendly = 'not_friendly'").first();
        const igFriendly = await env.DB.prepare("SELECT COUNT(*) as c FROM instagram_content WHERE grade_animal_friendly = 'friendly'").first();
        const igPartial = await env.DB.prepare("SELECT COUNT(*) as c FROM instagram_content WHERE grade_animal_friendly = 'partial'").first();
        const igNotFriendly = await env.DB.prepare("SELECT COUNT(*) as c FROM instagram_content WHERE grade_animal_friendly = 'not_friendly'").first();

        return jsonResponse({
          youtube: { total: ytCount.c, friendly: ytFriendly.c, partial: ytPartial.c, not_friendly: ytNotFriendly.c },
          instagram: { total: igCount.c, friendly: igFriendly.c, partial: igPartial.c, not_friendly: igNotFriendly.c },
        });
      }

      // GET /api/media/:key — serve media from KV
      if (method === 'GET' && path.startsWith('/api/media/')) {
        const key = path.split('/').pop();
        if (env.THUMBNAILS) {
          const val = await env.THUMBNAILS.get(key);
          if (val) {
            if (val.startsWith('data:')) {
              const parts = val.split(',');
              const mime = parts[0].match(/:(.*?);/)[1];
              const base64Data = parts[1];
              const binaryStr = atob(base64Data);
              const len = binaryStr.length;
              const bytes = new Uint8Array(len);
              for (let i = 0; i < len; i++) {
                bytes[i] = binaryStr.charCodeAt(i);
              }
              return new Response(bytes.buffer, {
                headers: {
                  ...corsHeaders,
                  'Content-Type': mime,
                  'Cache-Control': 'public, max-age=31536000',
                }
              });
            }
            return new Response(val, {
              headers: { ...corsHeaders, 'Content-Type': 'text/plain' }
            });
          }
        }
        return jsonResponse({ error: 'Media not found' }, 404);
      }

      // === PROTECTED ROUTES (require X-API-Secret) ===

      if (!isAuthorized(request, env)) {
        // Allow public GET routes above, block everything else except POST /api/submissions
        const isPublicSubmission = method === 'POST' && path === '/api/submissions';
        if (!isPublicSubmission && (method !== 'GET' || path.includes('/check/') || path.includes('/search-history') || path.includes('/logs'))) {
          return jsonResponse({ error: 'Unauthorized' }, 401);
        }
      }

      // POST /api/youtube — insert new youtube content
      if (method === 'POST' && path === '/api/youtube') {
        const body = await request.json();
        const stmt = await env.DB.prepare(`
          INSERT OR IGNORE INTO youtube_content (video_id, title, thumbnail_url, channel_name, channel_url, video_url, duration, published_at, grade_animal_friendly, grade_scientific, grade_emotional_manipulation, summary, raw_gemini_response, grading_method, status)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).bind(
          body.video_id, body.title, body.thumbnail_url, body.channel_name,
          body.channel_url, body.video_url, body.duration, body.published_at,
          body.grade_animal_friendly, body.grade_scientific, body.grade_emotional_manipulation,
          body.summary, body.raw_gemini_response, body.grading_method, body.status || 'graded'
        ).run();
        if (stmt.meta.changes === 0) {
          return jsonResponse({ success: true, duplicate: true, message: 'Video already exists' });
        }
        return jsonResponse({ success: true, id: stmt.meta.last_row_id }, 201);
      }

      // POST /api/instagram — insert new instagram content
      if (method === 'POST' && path === '/api/instagram') {
        const body = await request.json();
        
        let thumbnailUrl = body.thumbnail_url;
        if (body.thumbnail_base64 && env.THUMBNAILS) {
          const kvKey = `thumb_ig_${body.post_id}`;
          await env.THUMBNAILS.put(kvKey, body.thumbnail_base64);
          thumbnailUrl = `${url.origin}/api/media/${kvKey}`;
        }

        const stmt = await env.DB.prepare(`
          INSERT OR IGNORE INTO instagram_content (post_id, title, thumbnail_url, post_url, media_type, username, profile_url, published_at, grade_animal_friendly, grade_scientific, grade_emotional_manipulation, summary, raw_gemini_response, grading_method, status)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).bind(
          body.post_id, body.title, thumbnailUrl, body.post_url,
          body.media_type, body.username, body.profile_url, body.published_at,
          body.grade_animal_friendly, body.grade_scientific, body.grade_emotional_manipulation,
          body.summary, body.raw_gemini_response, body.grading_method, body.status || 'graded'
        ).run();
        if (stmt.meta.changes === 0) {
          return jsonResponse({ success: true, duplicate: true, message: 'Post already exists' });
        }
        return jsonResponse({ success: true, id: stmt.meta.last_row_id }, 201);
      }

      // PUT /api/youtube/:id — update youtube content
      if (method === 'PUT' && path.match(/^\/api\/youtube\/\d+$/)) {
        const id = path.split('/').pop();
        const body = await request.json();
        const fields = Object.keys(body).map(k => `${k} = ?`).join(', ');
        const values = Object.values(body);
        values.push(id);
        await env.DB.prepare(`UPDATE youtube_content SET ${fields}, updated_at = datetime('now') WHERE id = ?`).bind(...values).run();
        return jsonResponse({ success: true });
      }

      // PUT /api/instagram/:id — update instagram content
      if (method === 'PUT' && path.match(/^\/api\/instagram\/\d+$/)) {
        const id = path.split('/').pop();
        const body = await request.json();
        const fields = Object.keys(body).map(k => `${k} = ?`).join(', ');
        const values = Object.values(body);
        values.push(id);
        await env.DB.prepare(`UPDATE instagram_content SET ${fields}, updated_at = datetime('now') WHERE id = ?`).bind(...values).run();
        return jsonResponse({ success: true });
      }

      // DELETE /api/youtube/:id
      if (method === 'DELETE' && path.match(/^\/api\/youtube\/\d+$/)) {
        const id = path.split('/').pop();
        await env.DB.prepare('DELETE FROM youtube_content WHERE id = ?').bind(id).run();
        return jsonResponse({ success: true });
      }

      // DELETE /api/instagram/:id
      if (method === 'DELETE' && path.match(/^\/api\/instagram\/\d+$/)) {
        const id = path.split('/').pop();
        await env.DB.prepare('DELETE FROM instagram_content WHERE id = ?').bind(id).run();
        return jsonResponse({ success: true });
      }

      // GET /api/youtube/check/:video_id — dedup check
      if (method === 'GET' && path.match(/^\/api\/youtube\/check\/.+$/)) {
        const videoId = path.split('/').pop();
        const row = await env.DB.prepare('SELECT id FROM youtube_content WHERE video_id = ?').bind(videoId).first();
        return jsonResponse({ exists: !!row });
      }

      // GET /api/instagram/check/:post_id — dedup check
      if (method === 'GET' && path.match(/^\/api\/instagram\/check\/.+$/)) {
        const postId = path.split('/').pop();
        const row = await env.DB.prepare('SELECT id FROM instagram_content WHERE post_id = ?').bind(postId).first();
        return jsonResponse({ exists: !!row });
      }

      // POST /api/search-history — log search
      if (method === 'POST' && path === '/api/search-history') {
        const body = await request.json();
        await env.DB.prepare(`
          INSERT INTO search_history (platform, search_query, total_results, relevant_count, irrelevant_count, strategy_notes)
          VALUES (?, ?, ?, ?, ?, ?)
        `).bind(body.platform, body.search_query, body.total_results || 0, body.relevant_count || 0, body.irrelevant_count || 0, body.strategy_notes || '').run();
        return jsonResponse({ success: true }, 201);
      }

      // GET /api/search-history — get search history
      if (method === 'GET' && path === '/api/search-history') {
        const platform = url.searchParams.get('platform');
        let query = 'SELECT * FROM search_history';
        let params = [];
        if (platform) {
          query += ' WHERE platform = ?';
          params.push(platform);
        }
        query += ' ORDER BY created_at DESC LIMIT 100';
        const { results } = await env.DB.prepare(query).bind(...params).all();
        return jsonResponse({ data: results });
      }


      // GET /api/youtube/all — admin: get ALL youtube content (including skipped)
      if (method === 'GET' && path === '/api/youtube/all') {
        const { results } = await env.DB.prepare('SELECT * FROM youtube_content ORDER BY created_at DESC').all();
        return jsonResponse({ data: results });
      }

      // GET /api/instagram/all — admin: get ALL instagram content (including skipped)
      if (method === 'GET' && path === '/api/instagram/all') {
        const { results } = await env.DB.prepare('SELECT * FROM instagram_content ORDER BY created_at DESC').all();
        return jsonResponse({ data: results });
      }

      // POST /api/youtube/bulk-delete — delete multiple youtube items
      if (method === 'POST' && path === '/api/youtube/bulk-delete') {
        if (!isAuthorized(request, env)) {
          return jsonResponse({ error: 'Unauthorized' }, 401);
        }
        const body = await request.json();
        const ids = body.ids || [];
        if (ids.length === 0) {
          return jsonResponse({ error: 'No IDs provided' }, 400);
        }
        const placeholders = ids.map(() => '?').join(',');
        await env.DB.prepare(`DELETE FROM youtube_content WHERE id IN (${placeholders})`).bind(...ids).run();
        return jsonResponse({ success: true, deleted: ids.length });
      }

      // POST /api/instagram/bulk-delete — delete multiple instagram items
      if (method === 'POST' && path === '/api/instagram/bulk-delete') {
        if (!isAuthorized(request, env)) {
          return jsonResponse({ error: 'Unauthorized' }, 401);
        }
        const body = await request.json();
        const ids = body.ids || [];
        if (ids.length === 0) {
          return jsonResponse({ error: 'No IDs provided' }, 400);
        }
        const placeholders = ids.map(() => '?').join(',');
        await env.DB.prepare(`DELETE FROM instagram_content WHERE id IN (${placeholders})`).bind(...ids).run();
        return jsonResponse({ success: true, deleted: ids.length });
      }

      // POST /api/youtube/delete-all — delete ALL youtube items
      if (method === 'POST' && path === '/api/youtube/delete-all') {
        if (!isAuthorized(request, env)) {
          return jsonResponse({ error: 'Unauthorized' }, 401);
        }
        await env.DB.prepare('DELETE FROM youtube_content').run();
        return jsonResponse({ success: true, message: 'All YouTube content deleted' });
      }

      // POST /api/instagram/delete-all — delete ALL instagram items
      if (method === 'POST' && path === '/api/instagram/delete-all') {
        if (!isAuthorized(request, env)) {
          return jsonResponse({ error: 'Unauthorized' }, 401);
        }
        await env.DB.prepare('DELETE FROM instagram_content').run();
        return jsonResponse({ success: true, message: 'All Instagram content deleted' });
      }
      // POST /api/submissions — user submits a video link (PUBLIC with rate limiting)
      if (method === 'POST' && path === '/api/submissions') {
        const body = await request.json();
        if (!body.url || !body.platform) {
          return jsonResponse({ error: 'URL and platform are required' }, 400);
        }

        // Rate limiting logic
        const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
        const today = new Date().toISOString().split('T')[0];
        const rateLimitKey = `ratelimit_${ip}_${today}`;
        
        let currentCount = 0;
        if (env.THUMBNAILS) {
          const val = await env.THUMBNAILS.get(rateLimitKey);
          if (val) currentCount = parseInt(val, 10);
          
          if (currentCount >= 3) {
            return jsonResponse({ error: 'Rate limit exceeded: You can only submit 3 videos per day.' }, 429);
          }
        }

        // Insert submission
        const stmt = await env.DB.prepare(`
          INSERT INTO user_submissions (url, platform, status)
          VALUES (?, ?, 'pending')
        `).bind(body.url, body.platform).run();

        // Increment rate limit
        if (env.THUMBNAILS) {
          await env.THUMBNAILS.put(rateLimitKey, (currentCount + 1).toString(), { expirationTtl: 86400 });
        }

        return jsonResponse({ success: true, id: stmt.meta.last_row_id }, 201);
      }

      // === PROTECTED ROUTES (require X-API-Secret) ===

      // GET /api/submissions/pending — fetch oldest pending submission for a platform
      if (method === 'GET' && path === '/api/submissions/pending') {
        const platform = url.searchParams.get('platform');
        if (!platform) {
          return jsonResponse({ error: 'Platform query parameter is required' }, 400);
        }
        const row = await env.DB.prepare(`
          SELECT * FROM user_submissions 
          WHERE platform = ? AND status = 'pending' 
          ORDER BY created_at ASC LIMIT 1
        `).bind(platform).first();
        return jsonResponse({ data: row || null });
      }

      // PUT /api/submissions/:id/status — update status of a submission
      if (method === 'PUT' && path.match(/^\/api\/submissions\/\d+\/status$/)) {
        if (!isAuthorized(request, env)) {
          return jsonResponse({ error: 'Unauthorized' }, 401);
        }
        const id = path.split('/')[3];
        const body = await request.json();
        if (!body.status) {
          return jsonResponse({ error: 'Status is required' }, 400);
        }
        await env.DB.prepare('UPDATE user_submissions SET status = ? WHERE id = ?').bind(body.status, id).run();
        return jsonResponse({ success: true });
      }

      return jsonResponse({ error: 'Not found' }, 404);

    } catch (error) {
      return jsonResponse({ error: error.message }, 500);
    }
  },
};
