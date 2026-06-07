"""
Azure OpenAI-powered yoga coach with multi-step reasoning.
Built for Microsoft Agents League Contest @ AI Skills Fest 2026.

This module replaces the OpenRouter API with Azure OpenAI Service,
demonstrating advanced reasoning capabilities through structured prompts.
"""

import os
import json
from datetime import datetime

# Azure OpenAI SDK - install with: pip install openai
try:
    from openai import AzureOpenAI
    AZURE_OPENAI_AVAILABLE = True
except ImportError:
    AZURE_OPENAI_AVAILABLE = False
    print("⚠️  Azure OpenAI SDK not installed. Run: pip install openai")


class AzureAICoach:
    """
    Multi-step reasoning agent for personalized yoga coaching.
    
    Reasoning Flow:
    1. ANALYZE - Understand current pose errors and biomechanics
    2. CONTEXTUALIZE - Consider user's history, progress, and limitations
    3. RECOMMEND - Generate specific, actionable corrections
    4. ADAPT - Adjust difficulty and expectations based on performance
    """
    
    def __init__(self):
        if not AZURE_OPENAI_AVAILABLE:
            raise ImportError("Azure OpenAI SDK required")
        
        # Load Azure credentials from environment
        self.api_key = os.environ.get("AZURE_OPENAI_KEY")
        self.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "asanminds-coach")
        
        if not self.api_key or not self.endpoint:
            raise ValueError(
                "Missing Azure OpenAI credentials. Set AZURE_OPENAI_KEY and "
                "AZURE_OPENAI_ENDPOINT in your environment variables."
            )
        
        # Initialize Azure OpenAI client
        self.client = AzureOpenAI(
            api_key=self.api_key,
            api_version="2024-02-01",
            azure_endpoint=self.endpoint
        )
        
        print(f"✓ Azure AI Coach initialized (deployment: {self.deployment})")
    
    def analyze_pose_with_reasoning(
        self, 
        pose_name: str, 
        joint_errors: list,
        user_history: dict,
        user_profile: dict = None
    ) -> dict:
        """
        Perform multi-step reasoning analysis of a yoga pose attempt.
        
        Args:
            pose_name: Name of the yoga pose (e.g., "Vrikshasana")
            joint_errors: List of detected errors, e.g., 
                [{"joint": "left_knee", "error": "bent too much", "angle_diff": 15}]
            user_history: Dict with completed_asanas, activity_log, best_scores
            user_profile: Optional dict with limitations, experience_level
        
        Returns:
            Dict with:
                - response: Human-readable coaching advice
                - reasoning_steps: Structured breakdown of the reasoning process
                - confidence: How confident the agent is (0-1)
                - provider: "azure_openai" for contest tracking
        """
        
        # Build structured prompt with explicit reasoning steps
        system_prompt = """You are an expert yoga instructor AI with deep knowledge of:
- Biomechanics and human anatomy
- Yoga philosophy and proper alignment
- Adaptive teaching for different skill levels
- Injury prevention and safety

Analyze each pose attempt using this reasoning framework:
1. ANALYZE: Identify root causes of alignment errors
2. CONTEXTUALIZE: Consider the student's history and current ability
3. RECOMMEND: Provide specific, actionable corrections
4. ADAPT: Adjust difficulty or offer modifications if needed

Be encouraging, specific, and safety-focused."""

        # Format user context
        history_summary = self._summarize_history(user_history)
        errors_description = self._format_errors(joint_errors)
        profile_info = self._format_profile(user_profile) if user_profile else "No profile data"
        
        user_prompt = f"""Student is attempting: {pose_name}

DETECTED ERRORS:
{errors_description}

STUDENT HISTORY:
{history_summary}

STUDENT PROFILE:
{profile_info}

Please provide a multi-step analysis:

STEP 1 - ANALYZE:
What is the root cause of these alignment errors? Consider biomechanics.

STEP 2 - CONTEXTUALIZE:
Based on their history, is this expected? Are they progressing or struggling?

STEP 3 - RECOMMEND:
Give 2-3 specific corrections they should make right now.

STEP 4 - ADAPT:
Should we adjust difficulty? Offer modifications? What's the next step?

Format your response as JSON:
{{
  "analysis": "root cause explanation",
  "context": "how this relates to their journey",
  "corrections": ["specific fix 1", "specific fix 2", "specific fix 3"],
  "adaptations": "difficulty adjustments or modifications",
  "encouragement": "personalized motivation"
}}"""

        try:
            # Call Azure OpenAI with structured reasoning prompt
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=800,
                response_format={"type": "json_object"}  # Ensure JSON response
            )
            
            # Parse the reasoning steps
            content = response.choices[0].message.content
            reasoning_data = json.loads(content)
            
            # Build human-readable response
            readable_response = self._format_readable_response(reasoning_data)
            
            return {
                "success": True,
                "response": readable_response,
                "reasoning_steps": reasoning_data,
                "confidence": self._calculate_confidence(reasoning_data),
                "provider": "azure_openai",
                "model": self.deployment,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except json.JSONDecodeError as e:
            # Fallback if JSON parsing fails
            print(f"JSON decode error: {e}")
            return {
                "success": True,
                "response": content,  # Return raw text
                "reasoning_steps": {"raw": content},
                "confidence": 0.5,
                "provider": "azure_openai_fallback",
                "model": self.deployment,
                "timestamp": datetime.utcnow().isoformat()
            }
        
        except Exception as e:
            print(f"Azure OpenAI error: {e}")
            return {
                "success": False,
                "error": str(e),
                "provider": "azure_openai_error"
            }
    
    def _summarize_history(self, history: dict) -> str:
        """Convert user history into readable summary."""
        completed = history.get('completed_asanas', {})
        activity = history.get('activity_log', [])
        
        total_sessions = sum(completed.values())
        poses_mastered = len(completed)
        recent_activity = len([d for d in activity[-30:] if d])  # Last 30 days
        
        return f"""- Total practice sessions: {total_sessions}
- Poses mastered: {poses_mastered}
- Active days (last 30): {recent_activity}
- Recently practiced: {', '.join(list(completed.keys())[:5])}"""
    
    def _format_errors(self, errors: list) -> str:
        """Format joint errors into readable text."""
        if not errors:
            return "No major errors detected"
        
        formatted = []
        for err in errors[:5]:  # Top 5 errors only
            joint = err.get('joint', 'unknown')
            issue = err.get('error', 'misaligned')
            angle = err.get('angle_diff', 0)
            formatted.append(f"- {joint}: {issue} (off by {angle}°)")
        
        return "\n".join(formatted)
    
    def _format_profile(self, profile: dict) -> str:
        """Format user profile information."""
        return f"""- Experience level: {profile.get('experience_level', 'intermediate')}
- Known limitations: {', '.join(profile.get('limitations', ['none']))}
- Goals: {', '.join(profile.get('goals', ['general wellness']))}"""
    
    def _format_readable_response(self, data: dict) -> str:
        """Convert structured reasoning into friendly text."""
        response = f"""🧘 **Pose Analysis**

**Root Cause:** {data.get('analysis', 'Analysis unavailable')}

**Your Progress:** {data.get('context', 'Context unavailable')}

**Corrections to Try:**
"""
        for i, correction in enumerate(data.get('corrections', []), 1):
            response += f"{i}. {correction}\n"
        
        response += f"\n**Adjustments:** {data.get('adaptations', 'Keep practicing!')}"
        response += f"\n\n💪 {data.get('encouragement', 'You are doing great!')}"
        
        return response
    
    def _calculate_confidence(self, data: dict) -> float:
        """Estimate confidence based on reasoning completeness."""
        score = 0.0
        if data.get('analysis'): score += 0.25
        if data.get('context'): score += 0.25
        if data.get('corrections') and len(data['corrections']) >= 2: score += 0.25
        if data.get('adaptations'): score += 0.25
        return score


# Quick test function
if __name__ == "__main__":
    # Test the Azure AI Coach
    coach = AzureAICoach()
    
    result = coach.analyze_pose_with_reasoning(
        pose_name="Vrikshasana (Tree Pose)",
        joint_errors=[
            {"joint": "left_knee", "error": "bent inward", "angle_diff": 12},
            {"joint": "right_hip", "error": "tilted forward", "angle_diff": 8}
        ],
        user_history={
            "completed_asanas": {"Tadasana": 5, "Sukhasana": 3},
            "activity_log": ["2026-06-01", "2026-06-03", "2026-06-05"]
        },
        user_profile={
            "experience_level": "beginner",
            "limitations": ["tight hips"],
            "goals": ["improve balance"]
        }
    )
    
    print("\n=== Azure AI Coach Test ===")
    print(json.dumps(result, indent=2))
