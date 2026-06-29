from src.agents.tweet_generator import TweetGeneratorAgent


def test_clean_tweet_removes_repetitive_disclaimer_lines():
    agent = TweetGeneratorAgent.__new__(TweetGeneratorAgent)

    tweet = agent._clean_tweet(
        """Trimmed tech and kept cash near 30%.

Simulated portfolio. Not investment advice."""
    )

    assert tweet == "Trimmed tech and kept cash near 30%."
