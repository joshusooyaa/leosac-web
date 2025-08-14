"""
Utility functions for converting between rank integers and strings.
Matches the Ember user-rank transform implementation.
"""

def convert_rank_int_to_string(rank_int):
    """Convert rank integer to string (matching Ember user-rank transform)"""
    rank_mapping = {
        0: 'viewer', 
        1: 'viewer', 
        2: 'manager',
        3: 'supervisor',
        4: 'administrator'
    }
    return rank_mapping.get(rank_int, 'viewer')

def convert_rank_string_to_int(rank_string):
    """Convert rank string to integer (matching Ember user-rank transform)"""
    rank_mapping = {
        'viewer': 1,
        'manager': 2, 
        'supervisor': 3,
        'administrator': 4
    }
    # Default to viewer for unknown/legacy
    return rank_mapping.get(rank_string, 1)

# User ranks for UI selection (omit 'user')
USER_RANKS = ['viewer', 'manager', 'supervisor', 'administrator']