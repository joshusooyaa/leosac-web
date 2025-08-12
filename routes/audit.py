"""
Audit routes for Leosac Web GUI.
"""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from services.websocket_service import leosac_client
import logging

logger = logging.getLogger(__name__)

audit_bp = Blueprint('audit', __name__)

@audit_bp.route('/auditlog')
@login_required
def auditlog():
    """Display audit log page"""
    return render_template('auditlog.html')

@audit_bp.route('/api/audit/logs')
@login_required
def get_audit_logs():
    """API endpoint to get audit logs"""
    try:
        # Get query parameters
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 20, type=int)
        enabled_types = request.args.getlist('enabled_types')
        
        # If no types specified, get all types
        if not enabled_types:
            enabled_types = leosac_client.get_audit_event_types()
        
        logger.info(f"Fetching audit logs: page={page}, page_size={page_size}, types={enabled_types}")
        
        # Get audit logs from WebSocket service
        result = leosac_client.get_audit_logs(
            enabled_types=enabled_types,
            page=page,
            page_size=page_size
        )
        
        if result and 'entries' in result:
            return jsonify({
                'success': True,
                'data': result['entries'],
                'meta': result['meta']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to retrieve audit logs'
            }), 500
            
    except Exception as e:
        logger.error(f"Error getting audit logs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@audit_bp.route('/api/audit/event-types')
@login_required
def get_audit_event_types():
    """API endpoint to get available audit event types"""
    try:
        event_types = leosac_client.get_audit_event_types()
        return jsonify({
            'success': True,
            'data': event_types
        })
    except Exception as e:
        logger.error(f"Error getting audit event types: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500 