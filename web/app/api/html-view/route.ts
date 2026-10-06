import { NextRequest, NextResponse } from 'next/server';

const SYSTEM_PROMPT = `You are a content formatter. Convert the given bookmark/article content into a beautiful, readable HTML page.

RULES:
1. Output ONLY raw HTML. No markdown code blocks, no explanations.
2. Use a dark theme: background #0a0a0a, text #e0e0e0, accent #e74c3c.
3. Structure the content with clear sections: header, summary, key points, context.
4. Use proper typography: readable font sizes, line height, margins.
5. If there are links, make them clickable with the accent color.
6. Add a subtle header showing the source/author if available.
7. Keep it minimal and clean — this is for reading, not flashy design.
8. Use inline CSS in a <style> tag — no external dependencies.
9. The HTML should be a complete document with <!DOCTYPE html>.

Format the content to be actually pleasant to read, not just wrapped in HTML tags.`;

export async function POST(req: NextRequest) {
  try {
    const { title, text, author, url, summary, insights } = await req.json();
    
    if (!text && !summary) {
      return NextResponse.json({ error: 'No content provided' }, { status: 400 });
    }

    const content = `
Title: ${title || 'Untitled'}
Author: ${author || 'Unknown'}
URL: ${url || 'N/A'}

Content:
${text || summary}

${insights?.length ? `Key Insights:\n${insights.map((i: string) => `- ${i}`).join('\n')}` : ''}
`;

    const response = await fetch('https://openrouter.ai/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.OPENROUTER_API_KEY}`,
        'HTTP-Referer': 'https://example.com',
        'X-Title': 'Forger HTML View',
      },
      body: JSON.stringify({
        model: 'google/gemini-2.0-flash-001',
        messages: [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: `Convert this bookmark content into a styled HTML page:\n\n${content}` }
        ],
        temperature: 0.3,
        max_tokens: 4000,
      }),
    });

    if (!response.ok) {
      const err = await response.text();
      return NextResponse.json({ error: `API error: ${err}` }, { status: 500 });
    }

    const data = await response.json();
    let html = data.choices[0].message.content;
    
    // Clean up markdown code blocks if present
    html = html.replace(/^```html\n?/, '').replace(/\n?```$/, '').trim();
    
    return NextResponse.json({ html });
  } catch (err: any) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
