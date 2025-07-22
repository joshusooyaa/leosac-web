"""
Access Point management routes for Flask application.
"""
import logging
import traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from services.websocket_service import leosac_client

logger = logging.getLogger(__name__)

access_points_bp = Blueprint('access_points', __name__)

@access_points_bp.route('/access-points')
@login_required
def access_points_list():
    """List all access points"""
    logger.info("=== ACCESS POINTS LIST ROUTE CALLED ===")
    try:
        auth_state = leosac_client.get_auth_state()
        logger.debug(f"Auth state in access_points_list: {auth_state}")
        
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in access_points_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('access_points/list.html', access_points=[])
        
        logger.info("Calling leosac_client.get_access_points()")
        access_points = leosac_client.get_access_points()
        logger.info(f"Retrieved {len(access_points)} access points from WebSocket service")
        logger.debug(f"Access points data: {access_points}")
        
        return render_template('access_points/list.html', access_points=access_points)
    except Exception as e:
        logger.error(f'Error loading access points: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash(f'Error loading access points: {str(e)}', 'error')
        return render_template('access_points/list.html', access_points=[])

@access_points_bp.route('/access-points/create', methods=['GET', 'POST'])
@login_required
def access_points_create():
    """Create a new access point"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('access_points/create.html', access_point_data=request.form)
            
            # Get form data
            access_point_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'controller_module': request.form.get('controller_module', 'LEOSAC-BUILTIN-ACCESS-POINT')
            }
            
            # Validate required fields
            if not access_point_data['alias']:
                flash('Access point name is required', 'error')
                return render_template('access_points/create.html', access_point_data=access_point_data)
            
            # Create access point via WebSocket
            success, result = leosac_client.create_access_point(access_point_data)
            
            if success:
                flash('Access point created successfully!', 'success')
                return redirect(url_for('access_points.access_points_list'))
            else:
                error_msg = result.get('error', 'Unknown error')
                flash(f'Failed to create access point: {error_msg}', 'error')
                return render_template('access_points/create.html', access_point_data=access_point_data)
                
        except Exception as e:
            flash(f'Error creating access point: {str(e)}', 'error')
            return render_template('access_points/create.html', access_point_data=request.form)
    
    return render_template('access_points/create.html')

@access_points_bp.route('/access-points/<int:access_point_id>')
@login_required
def access_point_detail(access_point_id):
    """Show access point details"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('access_points.access_points_list'))
        
        access_point = leosac_client.get_access_point(access_point_id)
        if not access_point:
            flash('Access point not found', 'error')
            return redirect(url_for('access_points.access_points_list'))
        
        return render_template('access_points/detail.html', access_point=access_point)
    except Exception as e:
        logger.error(f'Error loading access point {access_point_id}: {str(e)}')
        flash(f'Error loading access point: {str(e)}', 'error')
        return redirect(url_for('access_points.access_points_list'))

@access_points_bp.route('/access-points/<int:access_point_id>/edit', methods=['GET', 'POST'])
@login_required
def access_point_edit(access_point_id):
    """Edit an access point"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('access_points.access_point_edit', access_point_id=access_point_id))
            
            # Get form data
            access_point_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'controller_module': request.form.get('controller_module')
            }
            
            # Validate required fields
            if not access_point_data['alias']:
                flash('Access point name is required', 'error')
                return redirect(url_for('access_points.access_point_edit', access_point_id=access_point_id))
            
            # Update access point via WebSocket
            success, result = leosac_client.update_access_point(access_point_id, access_point_data)
            
            if success:
                flash('Access point updated successfully!', 'success')
                return redirect(url_for('access_points.access_point_detail', access_point_id=access_point_id))
            else:
                error_msg = result.get('error', 'Unknown error')
                flash(f'Failed to update access point: {error_msg}', 'error')
                return redirect(url_for('access_points.access_point_edit', access_point_id=access_point_id))
                
        except Exception as e:
            flash(f'Error updating access point: {str(e)}', 'error')
            return redirect(url_for('access_points.access_point_edit', access_point_id=access_point_id))
    
    # Get access point data for the form
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('access_points.access_points_list'))
        
        access_point = leosac_client.get_access_point(access_point_id)
        if not access_point:
            flash('Access point not found', 'error')
            return redirect(url_for('access_points.access_points_list'))
        
        return render_template('access_points/edit.html', access_point=access_point)
    except Exception as e:
        logger.error(f'Error loading access point {access_point_id} for edit: {str(e)}')
        flash(f'Error loading access point: {str(e)}', 'error')
        return redirect(url_for('access_points.access_points_list'))

@access_points_bp.route('/access-points/<int:access_point_id>/delete', methods=['POST'])
@login_required
def access_point_delete(access_point_id):
    """Delete an access point"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('access_points.access_points_list'))
        
        # Delete access point via WebSocket
        success, result = leosac_client.delete_access_point(access_point_id)
        
        if success:
            flash('Access point deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error')
            flash(f'Failed to delete access point: {error_msg}', 'error')
            
    except Exception as e:
        logger.error(f'Error deleting access point {access_point_id}: {str(e)}')
        flash(f'Error deleting access point: {str(e)}', 'error')
    
    return redirect(url_for('access_points.access_points_list')) 