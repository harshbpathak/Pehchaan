import copy

import pytest


@pytest.fixture
def review():
    return copy.deepcopy(
        {
            "@type": "ClaimReview",
            "claimReviewed": "The town clock runs on moonlight.",
            "url": "https://checks.example/review/clock?utm_source=test",
            "datePublished": "2024-02-29",
            "author": {
                "@type": "Organization",
                "name": "Synthetic Test Publisher",
                "url": "https://checks.example/",
            },
            "reviewRating": {
                "alternateName": "Unsupported (synthetic test rating)",
                "ratingValue": 1,
                "bestRating": 5,
            },
            "itemReviewed": {"author": {"@type": "Person", "name": "Claim originator"}},
        }
    )
