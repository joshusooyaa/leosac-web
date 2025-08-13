"""
Zone management routes for Flask application.
"""
import logging
import traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from services.websocket_service import leosac_client

logger = logging.getLogger(__name__)

zones_bp = Blueprint('zones', __name__)


@zones_bp.route('/zones')
@login_required
def zones_list():
    """List all zones"""
    logger.info("=== ZONES LIST ROUTE CALLED ===")
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('zones/list.html', zones=[])
        zones = leosac_client.get_zones()
        return render_template('zones/list.html', zones=zones)
    except Exception as e:
        logger.error(f'Error loading zones: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash(f'Error loading zones: {str(e)}', 'error')
        return render_template('zones/list.html', zones=[])


@zones_bp.route('/zones/create', methods=['GET', 'POST'])
@login_required
def zones_create():
    """Create a new zone"""
    if request.method == 'POST':
        try:
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('zones/create.html', zone_data=request.form)

            alias = request.form.get('alias') or request.form.get('name')
            description = request.form.get('description', '')
            ztype = int(request.form.get('type', 1))
            doors = [int(d) for d in request.form.getlist('doors[]') if d]
            children = [int(z) for z in request.form.getlist('children[]') if z]

            if not alias:
                flash('Zone name is required', 'error')
                return render_template('zones/create.html', zone_data=request.form)

            zone_data = {
                'alias': alias,
                'description': description,
                'type': ztype,
                'doors': doors,
                'children': children,
            }

            success, result = leosac_client.create_zone(zone_data)
            if success:
                flash('Zone created successfully!', 'success')
                return redirect(url_for('zones.zones_list'))
            else:
                error_msg = result.get('error', 'Unknown error') if isinstance(result, dict) else 'Unknown error'
                flash(f'Failed to create zone: {error_msg}', 'error')
                return render_template('zones/create.html', zone_data=zone_data)

        except Exception as e:
            flash(f'Error creating zone: {str(e)}', 'error')
            return render_template('zones/create.html', zone_data=request.form)

    # For GET, provide door and zone lists to pick relationships
    try:
        doors = leosac_client.get_doors()
        zones = leosac_client.get_zones()
    except Exception:
        doors, zones = [], []
    return render_template('zones/create.html', doors=doors, zones=zones)


@zones_bp.route('/zones/<int:zone_id>')
@login_required
def zone_detail(zone_id):
    """Show zone details"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('zones.zones_list'))
        zone = leosac_client.get_zone(zone_id)
        if not zone:
            flash('Zone not found', 'error')
            return redirect(url_for('zones.zones_list'))
        return render_template('zones/detail.html', zone=zone)
    except Exception as e:
        logger.error(f'Error loading zone {zone_id}: {str(e)}')
        flash(f'Error loading zone: {str(e)}', 'error')
        return redirect(url_for('zones.zones_list'))


@zones_bp.route('/zones/<int:zone_id>/edit', methods=['GET', 'POST'])
@login_required
def zone_edit(zone_id):
    """Edit a zone"""
    if request.method == 'POST':
        try:
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('zones.zone_edit', zone_id=zone_id))

            alias = request.form.get('alias') or request.form.get('name')
            description = request.form.get('description', '')
            ztype = int(request.form.get('type', 1))
            doors = [int(d) for d in request.form.getlist('doors[]') if d]
            children = [int(z) for z in request.form.getlist('children[]') if z]

            if not alias:
                flash('Zone name is required', 'error')
                return redirect(url_for('zones.zone_edit', zone_id=zone_id))

            zone_data = {
                'alias': alias,
                'description': description,
                'type': ztype,
                'doors': doors,
                'children': children,
            }

            success, result = leosac_client.update_zone(zone_id, zone_data)
            if success:
                flash('Zone updated successfully!', 'success')
                return redirect(url_for('zones.zone_detail', zone_id=zone_id))
            else:
                error_msg = result.get('error', 'Unknown error') if isinstance(result, dict) else 'Unknown error'
                flash(f'Failed to update zone: {error_msg}', 'error')
                return redirect(url_for('zones.zone_edit', zone_id=zone_id))

        except Exception as e:
            flash(f'Error updating zone: {str(e)}', 'error')
            return redirect(url_for('zones.zone_edit', zone_id=zone_id))

    try:
        zone = leosac_client.get_zone(zone_id)
        doors = leosac_client.get_doors()
        zones = leosac_client.get_zones()
        return render_template('zones/edit.html', zone=zone, doors=doors, zones=zones)
    except Exception as e:
        logger.error(f'Error loading zone {zone_id} for edit: {str(e)}')
        flash(f'Error loading zone: {str(e)}', 'error')
        return redirect(url_for('zones.zones_list'))


@zones_bp.route('/zones/<int:zone_id>/delete', methods=['POST'])
@login_required
def zone_delete(zone_id):
    """Delete a zone"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('zones.zones_list'))

        success, result = leosac_client.delete_zone(zone_id)
        if success:
            flash('Zone deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error') if isinstance(result, dict) else 'Unknown error'
            flash(f'Failed to delete zone: {error_msg}', 'error')

    except Exception as e:
        logger.error(f'Error deleting zone {zone_id}: {str(e)}')
        flash(f'Error deleting zone: {str(e)}', 'error')

    return redirect(url_for('zones.zones_list'))



