"""
Wiegand Reader management routes for Flask application.
"""
import logging
import traceback
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from services.websocket_service import leosac_client

logger = logging.getLogger(__name__)

wiegand_readers_bp = Blueprint('wiegand_readers', __name__)

@wiegand_readers_bp.route('/wiegand-readers')
@login_required
def wiegand_readers_list():
    """List all Wiegand readers"""
    logger.info("=== WIEGAND READERS LIST ROUTE CALLED ===")
    try:
        auth_state = leosac_client.get_auth_state()
        logger.debug(f"Auth state in wiegand_readers_list: {auth_state}")
        
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in wiegand_readers_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return render_template('wiegand_readers/list.html', wiegand_readers=[])
        
        logger.info("Calling leosac_client.get_wiegand_readers()")
        wiegand_readers = leosac_client.get_wiegand_readers()
        logger.info(f"Retrieved {len(wiegand_readers)} Wiegand readers from WebSocket service")
        logger.debug(f"Wiegand readers data: {wiegand_readers}")
        
        return render_template('wiegand_readers/list.html', wiegand_readers=wiegand_readers)
    except Exception as e:
        logger.error(f'Error loading Wiegand readers: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash(f'Error loading Wiegand readers: {str(e)}', 'error')
        return render_template('wiegand_readers/list.html', wiegand_readers=[])

@wiegand_readers_bp.route('/wiegand-readers/create', methods=['GET', 'POST'])
@login_required
def wiegand_readers_create():
    """Create a new Wiegand reader"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return render_template('wiegand_readers/create.html', wiegand_reader_data=request.form)
            
            # Get form data
            wiegand_reader_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'mode': request.form.get('mode', 'SIMPLE_WIEGAND'),
                'gpio_high_id': request.form.get('gpio_high_id', ''),
                'gpio_low_id': request.form.get('gpio_low_id', ''),
                'green_led_id': request.form.get('green_led_id', ''),
                'buzzer_id': request.form.get('buzzer_id', ''),
                'pin_timeout': int(request.form.get('pin_timeout', 2500)),
                'pin_key_end': request.form.get('pin_key_end', '#')
            }
            
            # Validate required fields
            if not wiegand_reader_data['alias']:
                flash('Wiegand reader name is required', 'error')
                return render_template('wiegand_readers/create.html', wiegand_reader_data=wiegand_reader_data)
            
            # Create Wiegand reader via WebSocket
            success, result = leosac_client.create_wiegand_reader(wiegand_reader_data)
            
            if success:
                flash('Wiegand reader created successfully!', 'success')
                return redirect(url_for('wiegand_readers.wiegand_readers_list'))
            else:
                error_msg = result.get('error', 'Unknown error')
                flash(f'Failed to create Wiegand reader: {error_msg}', 'error')
                return render_template('wiegand_readers/create.html', wiegand_reader_data=wiegand_reader_data)
                
        except Exception as e:
            flash(f'Error creating Wiegand reader: {str(e)}', 'error')
            return render_template('wiegand_readers/create.html', wiegand_reader_data=request.form)
    
    return render_template('wiegand_readers/create.html')

@wiegand_readers_bp.route('/wiegand-readers/<int:reader_id>')
@login_required
def wiegand_reader_detail(reader_id):
    """Show Wiegand reader details"""
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('wiegand_readers.wiegand_readers_list'))
        
        wiegand_reader = leosac_client.get_wiegand_reader(reader_id)
        if not wiegand_reader:
            flash('Wiegand reader not found', 'error')
            return redirect(url_for('wiegand_readers.wiegand_readers_list'))
        
        return render_template('wiegand_readers/detail.html', wiegand_reader=wiegand_reader)
    except Exception as e:
        logger.error(f'Error loading Wiegand reader {reader_id}: {str(e)}')
        flash(f'Error loading Wiegand reader: {str(e)}', 'error')
        return redirect(url_for('wiegand_readers.wiegand_readers_list'))

@wiegand_readers_bp.route('/wiegand-readers/<int:reader_id>/edit', methods=['GET', 'POST'])
@login_required
def wiegand_reader_edit(reader_id):
    """Edit a Wiegand reader"""
    if request.method == 'POST':
        try:
            # Check if WebSocket client is connected
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('wiegand_readers.wiegand_reader_edit', reader_id=reader_id))
            
            # Get form data
            wiegand_reader_data = {
                'alias': request.form.get('alias'),
                'description': request.form.get('description', ''),
                'mode': request.form.get('mode'),
                'gpio_high_id': request.form.get('gpio_high_id', ''),
                'gpio_low_id': request.form.get('gpio_low_id', ''),
                'green_led_id': request.form.get('green_led_id', ''),
                'buzzer_id': request.form.get('buzzer_id', ''),
                'pin_timeout': int(request.form.get('pin_timeout', 2500)),
                'pin_key_end': request.form.get('pin_key_end', '#')
            }
            
            # Validate required fields
            if not wiegand_reader_data['alias']:
                flash('Wiegand reader name is required', 'error')
                return redirect(url_for('wiegand_readers.wiegand_reader_edit', reader_id=reader_id))
            
            # Update Wiegand reader via WebSocket
            success, result = leosac_client.update_wiegand_reader(reader_id, wiegand_reader_data)
            
            if success:
                flash('Wiegand reader updated successfully!', 'success')
                return redirect(url_for('wiegand_readers.wiegand_reader_detail', reader_id=reader_id))
            else:
                error_msg = result.get('error', 'Unknown error')
                flash(f'Failed to update Wiegand reader: {error_msg}', 'error')
                return redirect(url_for('wiegand_readers.wiegand_reader_edit', reader_id=reader_id))
                
        except Exception as e:
            flash(f'Error updating Wiegand reader: {str(e)}', 'error')
            return redirect(url_for('wiegand_readers.wiegand_reader_edit', reader_id=reader_id))
    
    # Get Wiegand reader data for the form
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('wiegand_readers.wiegand_readers_list'))
        
        wiegand_reader = leosac_client.get_wiegand_reader(reader_id)
        if not wiegand_reader:
            flash('Wiegand reader not found', 'error')
            return redirect(url_for('wiegand_readers.wiegand_readers_list'))
        
        return render_template('wiegand_readers/edit.html', wiegand_reader=wiegand_reader)
    except Exception as e:
        logger.error(f'Error loading Wiegand reader {reader_id} for edit: {str(e)}')
        flash(f'Error loading Wiegand reader: {str(e)}', 'error')
        return redirect(url_for('wiegand_readers.wiegand_readers_list'))

@wiegand_readers_bp.route('/wiegand-readers/<int:reader_id>/delete', methods=['POST'])
@login_required
def wiegand_reader_delete(reader_id):
    """Delete a Wiegand reader"""
    try:
        # Check if WebSocket client is connected
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('wiegand_readers.wiegand_readers_list'))
        
        # Delete Wiegand reader via WebSocket
        success, result = leosac_client.delete_wiegand_reader(reader_id)
        
        if success:
            flash('Wiegand reader deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error')
            flash(f'Failed to delete Wiegand reader: {error_msg}', 'error')
            
    except Exception as e:
        logger.error(f'Error deleting Wiegand reader {reader_id}: {str(e)}')
        flash(f'Error deleting Wiegand reader: {str(e)}', 'error')
    
    return redirect(url_for('wiegand_readers.wiegand_readers_list')) 