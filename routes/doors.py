"""
Door management routes for Flask application.
"""
import logging
import traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.permissions import has_permission
from services.websocket_service import leosac_client

logger = logging.getLogger(__name__)

doors_bp = Blueprint('doors', __name__)

@doors_bp.route('/doors')
@login_required
def doors_list():
    """List all doors"""
    logger.info("=== DOORS LIST ROUTE CALLED ===")
    try:
        auth_state = leosac_client.get_auth_state()
        logger.debug(f"Auth state in doors_list: {auth_state}")
        
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in doors_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('doors/list.html', doors=[])
        
        logger.info("Calling leosac_client.get_doors()")
        doors = leosac_client.get_doors()
        logger.info(f"Retrieved {len(doors)} doors from WebSocket service")
        logger.debug(f"Doors data: {doors}")
        
        return render_template('doors/list.html', doors=doors)
    except Exception as e:
        logger.error(f'Error loading doors: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash(f'Error loading doors: {str(e)}', 'error')
        return render_template('doors/list.html', doors=[])

@doors_bp.route('/doors/create', methods=['GET', 'POST'])
@login_required
def doors_create():
    """Create a new door"""
    if not has_permission(getattr(current_user, 'rank', 'user'), 'doors.create'):
        flash('You do not have permission to create doors.', 'error')
        return redirect(url_for('doors.doors_list'))
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('doors/create.html', door_data=request.form)
            
            # Get form data
            door_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'access_point_id': request.form.get('access_point_id') or None
            }
            
            # Validate required fields
            if not door_data['alias']:
                flash('Door name is required', 'error')
                return render_template('doors/create.html', door_data=door_data)
            
            # Convert access_point_id to int if provided
            if door_data['access_point_id']:
                try:
                    door_data['access_point_id'] = int(door_data['access_point_id'])
                except ValueError:
                    flash('Invalid access point ID', 'error')
                    return render_template('doors/create.html', door_data=door_data)
            
            # Create door via WebSocket
            success, result = leosac_client.create_door(door_data)
            
            if success:
                flash('Door created successfully!', 'success')
                return redirect(url_for('doors.doors_list'))
            else:
                error_msg = result.get('error', 'Unknown error')
                flash(f'Failed to create door: {error_msg}', 'error')
                return render_template('doors/create.html', door_data=door_data)
                
        except Exception as e:
            flash(f'Error creating door: {str(e)}', 'error')
            return render_template('doors/create.html', door_data=request.form)
    
    # Get access points for the form
    try:
        access_points = leosac_client.get_access_points()
    except Exception as e:
        logger.error(f'Error loading access points: {str(e)}')
        access_points = []
    
    return render_template('doors/create.html', access_points=access_points)

@doors_bp.route('/doors/<int:door_id>')
@login_required
def door_detail(door_id):
    """Show door details"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('doors.doors_list'))
        
        door = leosac_client.get_door(door_id)
        if not door:
            flash('Door not found', 'error')
            return redirect(url_for('doors.doors_list'))
        
        return render_template('doors/detail.html', door=door)
    except Exception as e:
        logger.error(f'Error loading door {door_id}: {str(e)}')
        flash(f'Error loading door: {str(e)}', 'error')
        return redirect(url_for('doors.doors_list'))

@doors_bp.route('/doors/<int:door_id>/edit', methods=['GET', 'POST'])
@login_required
def door_edit(door_id):
    """Edit a door"""
    if not has_permission(getattr(current_user, 'rank', 'user'), 'doors.update'):
        flash('You do not have permission to edit doors.', 'error')
        return redirect(url_for('doors.doors_list'))
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('doors.door_edit', door_id=door_id))
            
            # Get form data
            door_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'access_point_id': request.form.get('access_point_id') or None
            }
            
            # Validate required fields
            if not door_data['alias']:
                flash('Door name is required', 'error')
                return redirect(url_for('doors.door_edit', door_id=door_id))
            
            # Convert access_point_id to int if provided
            if door_data['access_point_id']:
                try:
                    door_data['access_point_id'] = int(door_data['access_point_id'])
                except ValueError:
                    flash('Invalid access point ID', 'error')
                    return redirect(url_for('doors.door_edit', door_id=door_id))
            
            # Update door via WebSocket
            success, result = leosac_client.update_door(door_id, door_data)
            
            if success:
                flash('Door updated successfully!', 'success')
                return redirect(url_for('doors.door_detail', door_id=door_id))
            else:
                error_msg = result.get('error', 'Unknown error')
                flash(f'Failed to update door: {error_msg}', 'error')
                return redirect(url_for('doors.door_edit', door_id=door_id))
                
        except Exception as e:
            flash(f'Error updating door: {str(e)}', 'error')
            return redirect(url_for('doors.door_edit', door_id=door_id))
    
    # Get door data for the form
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('doors.doors_list'))
        
        door = leosac_client.get_door(door_id)
        if not door:
            flash('Door not found', 'error')
            return redirect(url_for('doors.doors_list'))
        
        # Get access points for the form
        access_points = leosac_client.get_access_points()
        
        return render_template('doors/edit.html', door=door, access_points=access_points)
    except Exception as e:
        logger.error(f'Error loading door {door_id} for edit: {str(e)}')
        flash(f'Error loading door: {str(e)}', 'error')
        return redirect(url_for('doors.doors_list'))

@doors_bp.route('/doors/<int:door_id>/delete', methods=['POST'])
@login_required
def door_delete(door_id):
    """Delete a door"""
    if not has_permission(getattr(current_user, 'rank', 'user'), 'doors.delete'):
        flash('You do not have permission to delete doors.', 'error')
        return redirect(url_for('doors.doors_list'))
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('doors.doors_list'))
        
        # Delete door via WebSocket
        success, result = leosac_client.delete_door(door_id)
        
        if success:
            flash('Door deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error')
            flash(f'Failed to delete door: {error_msg}', 'error')
            
    except Exception as e:
        logger.error(f'Error deleting door {door_id}: {str(e)}')
        flash(f'Error deleting door: {str(e)}', 'error')
    
    return redirect(url_for('doors.doors_list')) 