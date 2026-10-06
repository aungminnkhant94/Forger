"""Similar bookmark detection to prevent duplicate topics."""

from difflib import SequenceMatcher
from typing import List, Dict, Any

def similarity_score(str1: str, str2: str) -> float:
    """Calculate string similarity (0-1)."""
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()

def find_similar_bookmarks(
    new_title: str,
    new_tags: List[str],
    new_text: str,
    existing_bookmarks: List[Dict[str, Any]],
    threshold: float = 0.6
) -> List[Dict[str, Any]]:
    """
    Find bookmarks similar to the new one.
    
    Returns list of similar bookmarks with similarity scores.
    """
    similar = []
    
    for bookmark in existing_bookmarks:
        score = 0.0
        reasons = []
        
        # Tag overlap (high weight)
        existing_tags = set(bookmark.get('tags', []))
        new_tags_set = set(new_tags)
        if existing_tags and new_tags_set:
            tag_overlap = len(existing_tags & new_tags_set) / max(len(existing_tags), len(new_tags_set))
            if tag_overlap >= 0.5:  # 50% tag overlap
                score += tag_overlap * 0.4  # 40% weight
                reasons.append(f"{int(tag_overlap*100)}% tag overlap")
        
        # Title similarity
        title_sim = similarity_score(new_title, bookmark.get('title', ''))
        if title_sim >= 0.5:
            score += title_sim * 0.35  # 35% weight
            reasons.append(f"{int(title_sim*100)}% title similarity")
        
        # Content similarity (check first 500 chars)
        content_sim = similarity_score(
            new_text[:500], 
            bookmark.get('text', '')[:500]
        )
        if content_sim >= 0.4:
            score += content_sim * 0.25  # 25% weight
            reasons.append(f"{int(content_sim*100)}% content similarity")
        
        # If score above threshold, add to similar list
        if score >= threshold:
            similar.append({
                'bookmark': bookmark,
                'score': score,
                'reasons': reasons
            })
    
    # Sort by similarity score
    similar.sort(key=lambda x: x['score'], reverse=True)
    return similar

def check_duplicate_topic(
    url: str,
    title: str,
    tags: List[str],
    text: str,
    existing_bookmarks: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Check if similar bookmark already exists.
    
    Returns:
        {
            'is_duplicate': bool,
            'similar': List of similar bookmarks,
            'message': str
        }
    """
    # First check exact URL
    for b in existing_bookmarks:
        if b['url'] == url:
            return {
                'is_duplicate': True,
                'similar': [{'bookmark': b, 'score': 1.0, 'reasons': ['Exact URL match']}],
                'message': f"Exact duplicate: {b['title'][:50]}..."
            }
    
    # Check for similar content
    similar = find_similar_bookmarks(title, tags, text, existing_bookmarks)
    
    if similar:
        top_match = similar[0]
        return {
            'is_duplicate': False,  # Not exact duplicate, but similar
            'similar': similar[:3],  # Top 3 similar
            'message': f"Similar to: {top_match['bookmark']['title'][:50]}... ({', '.join(top_match['reasons'])})"
        }
    
    return {
        'is_duplicate': False,
        'similar': [],
        'message': None
    }
