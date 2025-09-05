from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from utils.permissions import has_permission
from services.websocket_service import leosac_client
import re
import logging
logger = logging.getLogger(__name__)
import traceback

schedules_bp = Blueprint('schedules', __name__)

def pad_time(timestr):
    # Accepts '0:0', '6:0', '12:59', etc. Returns '00:00', '06:00', '12:59'
    if not timestr:
        return ''
    parts = str(timestr).split(':')
    if len(parts) == 2:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return timestr

def group_timeframes_for_display(timeframes):
    if not timeframes:
        return []
    grouped = {}
    for tf in timeframes:
        start_time = pad_time(tf.get('start-time') or tf.get('start_time'))
        end_time = pad_time(tf.get('end-time') or tf.get('end_time'))
        day = tf.get('day')
        if start_time and end_time and day is not None:
            key = f"{start_time}-{end_time}"
            if key not in grouped:
                grouped[key] = {
                    'start_time': start_time,
                    'end_time': end_time,
                    'days': set()
                }
            grouped[key]['days'].add(int(day))
    result = []
    for i, (key, data) in enumerate(grouped.items()):
        timeframe = {
            'id': i,
            'start_time': data['start_time'],
            'end_time': data['end_time'],
            'days': sorted(list(data['days']))
        }
        result.append(timeframe)
    return result

@schedules_bp.route('/schedules')
@login_required
def schedules_list():
    try:
        logger.info('--- schedules_list called ---')
        auth_state = leosac_client.get_auth_state()
        logger.info(f'Auth state: {auth_state}')
        if not auth_state['connected']:
            logger.warning('WebSocket connection not available in schedules_list route.')
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('index'))
        schedules = leosac_client.get_schedules()
        logger.info(f'Schedules returned: {schedules}')
        return render_template('schedules/list.html', schedules=schedules)
    except Exception as e:
        logger.error(f'Error loading schedules: {str(e)}')
        logger.error(f'Traceback: {traceback.format_exc()}')
        flash('Error loading schedules. Please try again.', 'error')
        return redirect(url_for('index'))

@schedules_bp.route('/schedules/create', methods=['GET', 'POST'])
@login_required
def schedules_create():
    if not has_permission(getattr(current_user, 'rank', 'user'), 'schedules.create'):
        flash('You do not have permission to create schedules.', 'error')
        return redirect(url_for('schedules.schedules_list'))
    if request.method == 'POST':
        try:
            auth_state = leosac_client.get_auth_state()
            if not auth_state['connected']:
                flash('WebSocket connection not available. Please try again.', 'error')
                return redirect(url_for('schedules.schedules_list'))
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            if not name:
                flash('Schedule name is required.', 'error')
                return render_template('schedules/create.html')
            if len(name) < 3:
                flash('Schedule name must be at least 3 characters long.', 'error')
                return render_template('schedules/create.html')
            if len(name) > 50:
                flash('Schedule name must be no more than 50 characters long.', 'error')
                return render_template('schedules/create.html')
            if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
                flash('Schedule name can only contain letters, numbers, underscores (_), hyphens (-), and periods (.). No spaces or other characters are allowed.', 'error')
                return render_template('schedules/create.html')
            timeframes = []
            timeframe_counter = 0
            while f'timeframes[{timeframe_counter}][start_time]' in request.form:
                start_time = request.form.get(f'timeframes[{timeframe_counter}][start_time]')
                end_time = request.form.get(f'timeframes[{timeframe_counter}][end_time]')
                if start_time and end_time:
                    selected_days = []
                    for day_name, day_value in [
                        ('sunday', 0), ('monday', 1), ('tuesday', 2), ('wednesday', 3), 
                        ('thursday', 4), ('friday', 5), ('saturday', 6)
                    ]:
                        if f'timeframes[{timeframe_counter}][days][{day_name}]' in request.form:
                            selected_days.append(day_value)
                    for day in selected_days:
                        timeframe = {
                            'id': len(timeframes),
                            'start-time': start_time,
                            'end-time': end_time,
                            'day': day
                        }
                        timeframes.append(timeframe)
                timeframe_counter += 1
            schedule_data = {
                'name': name,
                'description': description,
                'timeframes': timeframes
            }
            success, result = leosac_client.create_schedule(schedule_data)
            if success:
                flash('Schedule created successfully!', 'success')
                return redirect(url_for('schedules.schedule_view', schedule_id=result['id']))
            else:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to create schedule: {error_msg}', 'error')
                return render_template('schedules/create.html')
        except Exception as e:
            flash('Error creating schedule. Please try again.', 'error')
            return render_template('schedules/create.html')
    return render_template('schedules/create.html')

@schedules_bp.route('/schedules/<int:schedule_id>')
@login_required
def schedule_view(schedule_id):
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        schedule = leosac_client.get_schedule(schedule_id)
        if schedule:
            if schedule.get('timeframes'):
                schedule['timeframes'] = group_timeframes_for_display(schedule['timeframes'])

            # Build label maps for display
            try:
                users_list = leosac_client.get_users()
            except Exception:
                users_list = []
            user_labels = {
                u['id']: f"{u.get('username','User')} ({u.get('firstname','')} {u.get('lastname','')}).strip()".replace('()','')
                for u in users_list if isinstance(u, dict) and u.get('id') is not None
            }

            try:
                groups_list = leosac_client.get_groups()
            except Exception:
                groups_list = []
            group_labels = {g['id']: g.get('name','Group') for g in groups_list if isinstance(g, dict) and g.get('id') is not None}

            try:
                credentials_list = leosac_client.get_credentials()
            except Exception:
                credentials_list = []
            credential_labels = {
                c['id']: f"{c.get('alias','Credential')} ({c.get('type','')})".strip()
                for c in credentials_list if isinstance(c, dict) and c.get('id') is not None
            }

            try:
                doors_list = leosac_client.get_doors()
            except Exception:
                doors_list = []
            def _door_alias(d):
                if not isinstance(d, dict):
                    return 'Door'
                attrs = d.get('attributes', {}) or {}
                return attrs.get('alias') or d.get('alias') or 'Door'
            door_labels = {d.get('id'): _door_alias(d) for d in doors_list if d.get('id') is not None}

            try:
                zones_list = leosac_client.get_zones()
            except Exception:
                zones_list = []
            zone_labels = {z.get('id'): (z.get('attributes', {}) or {}).get('alias') or f"Zone {z.get('id')}" for z in zones_list if isinstance(z, dict) and z.get('id') is not None}

            return render_template('schedules/view.html', schedule=schedule,
                                   user_labels=user_labels,
                                   group_labels=group_labels,
                                   credential_labels=credential_labels,
                                   door_labels=door_labels,
                                   zone_labels=zone_labels)
        else:
            flash('Schedule not found.', 'error')
            return redirect(url_for('schedules.schedules_list'))
    except Exception as e:
        flash('Error loading schedule. Please try again.', 'error')
        return redirect(url_for('schedules.schedules_list'))

@schedules_bp.route('/schedules/<int:schedule_id>/edit', methods=['GET', 'POST'])
@login_required
def schedule_edit(schedule_id):
    if not has_permission(getattr(current_user, 'rank', 'user'), 'schedules.update'):
        flash('You do not have permission to edit schedules.', 'error')
        return redirect(url_for('schedules.schedules_list'))
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        schedule = leosac_client.get_schedule(schedule_id)
        if not schedule:
            flash('Schedule not found.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        users = leosac_client.get_users()
        groups = leosac_client.get_groups()
        credentials = leosac_client.get_credentials()
        doors = leosac_client.get_doors()
        zones = leosac_client.get_zones()
        if schedule.get('timeframes'):
            schedule['timeframes'] = group_timeframes_for_display(schedule['timeframes'])
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            if not name:
                flash('Schedule name is required.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if len(name) < 3:
                flash('Schedule name must be at least 3 characters long.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if len(name) > 50:
                flash('Schedule name must be no more than 50 characters long.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            if not re.match(r'^[a-zA-Z0-9_.-]+$', name):
                flash('Schedule name can only contain letters, numbers, underscores (_), hyphens (-), and periods (.). No spaces or other characters are allowed.', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
            timeframes = []
            timeframe_counter = 0
            while f'timeframes[{timeframe_counter}][start_time]' in request.form:
                start_time = request.form.get(f'timeframes[{timeframe_counter}][start_time]')
                end_time = request.form.get(f'timeframes[{timeframe_counter}][end_time]')
                if start_time and end_time:
                    selected_days = []
                    for day_name, day_value in [
                        ('sunday', 0), ('monday', 1), ('tuesday', 2), ('wednesday', 3), 
                        ('thursday', 4), ('friday', 5), ('saturday', 6)
                    ]:
                        if f'timeframes[{timeframe_counter}][days][{day_name}]' in request.form:
                            selected_days.append(day_value)
                    for day in selected_days:
                        timeframe = {
                            'id': len(timeframes),
                            'start-time': start_time,
                            'end-time': end_time,
                            'day': day
                        }
                        timeframes.append(timeframe)
                timeframe_counter += 1
            mapping_data = []
            mapping_indices = set()
            import re as _re
            for key in request.form.keys():
                if key.startswith('mappings['):
                    m = _re.match(r'mappings\[(\d+)\]', key)
                    if m:
                        mapping_indices.add(int(m.group(1)))
            
            # Process each mapping separately to preserve individual mappings
            for idx in sorted(mapping_indices):
                alias = request.form.get(f'mappings[{idx}][alias]', '').strip()
                users_selected = request.form.getlist(f'mappings[{idx}][users][]')
                groups_selected = request.form.getlist(f'mappings[{idx}][groups][]')
                credentials_selected = request.form.getlist(f'mappings[{idx}][credentials][]')
                doors_selected = request.form.getlist(f'mappings[{idx}][doors][]')
                zones_selected = request.form.getlist(f'mappings[{idx}][zones][]')
                
                # Convert to integers and filter out empty values
                users = [int(uid) for uid in users_selected if uid and uid.strip()]
                groups = [int(gid) for gid in groups_selected if gid and gid.strip()]
                credentials = [int(cid) for cid in credentials_selected if cid and cid.strip()]
                doors = [int(did) for did in doors_selected if did and did.strip()]
                zones = [int(zid) for zid in zones_selected if zid and zid.strip()]
                
                # Only add mapping if it has an alias and at least one selection
                if alias and (users or groups or credentials or doors or zones):
                    mapping = {
                        'alias': alias,
                        'users': users,
                        'groups': groups,
                        'credentials': credentials,
                        'doors': doors,
                        'zones': zones
                    }
                    mapping_data.append(mapping)
            schedule_data = {
                'name': name,
                'description': description,
                'timeframes': timeframes
            }
            success, result = leosac_client.update_schedule(schedule_id, schedule_data, mapping_data)
            if success:
                flash('Schedule updated successfully!', 'success')
                return redirect(url_for('schedules.schedule_view', schedule_id=schedule_id))
            else:
                error_msg = result.get('error', 'Unknown error occurred')
                flash(f'Failed to update schedule: {error_msg}', 'error')
                return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors)
        return render_template('schedules/edit.html', schedule=schedule, users=users, groups=groups, credentials=credentials, doors=doors, zones=zones)
    except Exception as e:
        flash('Error editing schedule. Please try again.', 'error')
        return redirect(url_for('schedules.schedules_list'))

@schedules_bp.route('/schedules/<int:schedule_id>/delete', methods=['POST'])
@login_required
def schedule_delete(schedule_id):
    if not has_permission(getattr(current_user, 'rank', 'user'), 'schedules.delete'):
        flash('You do not have permission to delete schedules.', 'error')
        return redirect(url_for('schedules.schedules_list'))
    try:
        auth_state = leosac_client.get_auth_state()
        if not auth_state['connected']:
            flash('WebSocket connection not available. Please try again.', 'error')
            return redirect(url_for('schedules.schedules_list'))
        success, result = leosac_client.delete_schedule(schedule_id)
        if success:
            flash('Schedule deleted successfully!', 'success')
        else:
            error_msg = result.get('error', 'Unknown error occurred')
            flash(f'Failed to delete schedule: {error_msg}', 'error')
        return redirect(url_for('schedules.schedules_list'))
    except Exception as e:
        flash('Error deleting schedule. Please try again.', 'error')
        return redirect(url_for('schedules.schedules_list')) 