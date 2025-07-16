"""
Utility functions for converting between rank integers and strings.
Matches the Ember user-rank transform implementation.
"""

def convert_rank_int_to_string(rank_int):
    """Convert rank integer to string (matching Ember user-rank transform)"""
    rank_mapping = {
        0: 'user',
        1: 'viewer', 
        2: 'manager',
        3: 'supervisor',
        4: 'administrator'
    }
    return rank_mapping.get(rank_int, 'user')

def convert_rank_string_to_int(rank_string):
    """Convert rank string to integer (matching Ember user-rank transform)"""
    rank_mapping = {
        'user': 0,
        'viewer': 1,
        'manager': 2, 
        'supervisor': 3,
        'administrator': 4
    }
    return rank_mapping.get(rank_string, 0)

# User ranks matching Ember implementation
USER_RANKS = ['user', 'viewer', 'manager', 'supervisor', 'administrator'] 