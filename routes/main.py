"""
Main routes for Flask application.
"""
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from config.settings import LEOSAC_ADDR

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
@login_required
def index():
    return render_template('index.html', user=current_user, config={'LEOSAC_ADDR': LEOSAC_ADDR})

@main_bp.route('/status')
def status():
    """Check WebSocket connection status"""
    from services.websocket_service import leosac_client
    return leosac_client.get_auth_state()

# Overview routes
@main_bp.route('/system-overview')
@login_required
def system_overview():
    return render_template('system_overview.html')

@main_bp.route('/access-overview')
@login_required
def access_overview():
    return render_template('access_overview.html')

@main_bp.route('/zone-overview')
@login_required
def zone_overview():
    return render_template('zone_overview.html')

# Access management routes
@main_bp.route('/groups')
@login_required
def groups_list():
    return render_template('groups/list.html')

@main_bp.route('/groups/create')
@login_required
def groups_create():
    return render_template('groups/create.html')

@main_bp.route('/credentials')
@login_required
def credentials_list():
    return render_template('credentials/list.html')

@main_bp.route('/credentials/rfid/create')
@login_required
def credentials_rfid_create():
    return render_template('credentials/rfid_create.html')

@main_bp.route('/credentials/pin/create')
@login_required
def credentials_pin_create():
    return render_template('credentials/pin_create.html')

@main_bp.route('/schedules')
@login_required
def schedules_list():
    return render_template('schedules/list.html')

@main_bp.route('/schedules/create')
@login_required
def schedules_create():
    return render_template('schedules/create.html')

# Hardware management routes
@main_bp.route('/zones')
@login_required
def zones_list():
    return render_template('zones/list.html')

@main_bp.route('/zones/create')
@login_required
def zones_create():
    return render_template('zones/create.html')

@main_bp.route('/doors')
@login_required
def doors_list():
    return render_template('doors/list.html')

@main_bp.route('/doors/create')
@login_required
def doors_create():
    return render_template('doors/create.html')

@main_bp.route('/access-points')
@login_required
def access_points_list():
    return render_template('access_points/list.html')

@main_bp.route('/access-points/create')
@login_required
def access_points_create():
    return render_template('access_points/create.html')

@main_bp.route('/updates')
@login_required
def updates():
    return render_template('updates.html')

# System routes
@main_bp.route('/auditlog')
@login_required
def auditlog():
    return render_template('auditlog.html')

@main_bp.route('/settings')
@login_required
def settings():
    return render_template('settings.html') 

@main_bp.route('/help')
@login_required
def help_page():
    return render_template('help.html')

# Dashboard API
@main_bp.route('/api/dashboard/summary')
@login_required
def dashboard_summary():
    """Return lightweight summary counts for dashboard cards."""
    try:
        from services.websocket_service import leosac_client
        # Connection status
        auth_state = leosac_client.get_auth_state() or {}
        connected = bool(auth_state.get('connected'))

        # Basic counts (safe fallbacks)
        try:
            users = leosac_client.get_users() or []
        except Exception:
            users = []
        try:
            groups = leosac_client.get_groups() or []
        except Exception:
            groups = []
        try:
            credentials = leosac_client.get_credentials() or []
        except Exception:
            credentials = []
        try:
            doors = leosac_client.get_doors() or []
        except Exception:
            doors = []

        return jsonify({
            'success': True,
            'connected': connected,
            'counts': {
                'users': len(users),
                'groups': len(groups),
                'credentials': len(credentials),
                'doors': len(doors)
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500