

ROLE_PERMISSIONS = {
    "Citizen": [
        "view_risk_map", 
        "view_social_feed"
    ],
    "City": [
        "view_city_dashboard",
        "view_risk_map", 
        "view_social_feed"
    ],
    "Authority": [
        "view_risk_map", 
        "view_social_feed", 
        "view_basins_data", 
        "view_system_logs",
        "view_city_dashboard"
    ]
}

def has_access(role: str, feature: str) -> bool:
    """
    Checks if a specific role has permission to access a feature.
    """
    allowed_features = ROLE_PERMISSIONS.get(role, [])
    return feature in allowed_features