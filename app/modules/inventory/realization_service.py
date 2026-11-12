"""
ProductionRealizationService - CRUD and calculation logic for production realization logging
Phase 3: Detailed Production Realization (bertahap logging)
"""

from datetime import datetime, date
from sqlalchemy import desc, and_
from app.core.db import db_session
from app.modules.inventory.models import ProductionRealization, ProductionTarget, DailyProductionPlan
from app.shared.utils import generate_uuid
import json

class ProductionRealizationService:
    """Service for managing production realizations (bertahap progress tracking)"""
    
    @staticmethod
    def create_realization(target_id, tanggal, produced_qty, batch_number=None, notes=None, created_by=None):
        """
        Create a new production realization entry
        
        Args:
            target_id: Production target ID
            tanggal: Date of production (date object)
            produced_qty: Quantity produced in this batch
            batch_number: Batch sequence number (auto-calculate if None)
            notes: Optional notes
            created_by: User ID of creator
            
        Returns:
            ProductionRealization instance
        """
        # Get target to validate
        target = db_session.query(ProductionTarget).filter(ProductionTarget.id == target_id).first()
        if not target:
            raise ValueError(f"ProductionTarget {target_id} not found")
        
        # Auto-calculate batch_number if not provided
        if batch_number is None:
            last_batch = db_session.query(ProductionRealization).filter(
                and_(
                    ProductionRealization.target_id == target_id,
                    ProductionRealization.tanggal == tanggal
                )
            ).order_by(desc(ProductionRealization.batch_number)).first()
            batch_number = (last_batch.batch_number + 1) if last_batch else 1
        
        realization = ProductionRealization(
            id=generate_uuid(),
            target_id=target_id,
            tanggal=tanggal,
            batch_number=batch_number,
            produced_qty=produced_qty,
            notes=notes,
            status='in_progress',  # Default to in_progress
            created_by=created_by,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        
        db_session.add(realization)
        db_session.commit()
        
        return realization
    
    @staticmethod
    def get_realization(realization_id):
        """Get a production realization by ID"""
        return db_session.query(ProductionRealization).filter(
            ProductionRealization.id == realization_id
        ).first()
    
    @staticmethod
    def list_realizations_for_target(target_id, tanggal=None):
        """
        List all realizations for a target, optionally filtered by date
        
        Args:
            target_id: Production target ID
            tanggal: Optional date filter
            
        Returns:
            List of ProductionRealization instances
        """
        query = db_session.query(ProductionRealization).filter(
            ProductionRealization.target_id == target_id
        )
        
        if tanggal:
            query = query.filter(ProductionRealization.tanggal == tanggal)
        
        return query.order_by(
            ProductionRealization.tanggal.desc(),
            ProductionRealization.batch_number.asc()
        ).all()
    
    @staticmethod
    def list_realizations_for_plan(plan_id, tanggal=None):
        """
        List all realizations for a daily plan
        
        Args:
            plan_id: Daily production plan ID
            tanggal: Optional date filter
            
        Returns:
            List of ProductionRealization instances
        """
        query = db_session.query(ProductionRealization).join(
            ProductionTarget, ProductionRealization.target_id == ProductionTarget.id
        ).filter(ProductionTarget.plan_id == plan_id)
        
        if tanggal:
            query = query.filter(ProductionRealization.tanggal == tanggal)
        
        return query.order_by(
            ProductionRealization.tanggal.desc(),
            ProductionRealization.batch_number.asc()
        ).all()
    
    @staticmethod
    def update_realization(realization_id, **kwargs):
        """
        Update a production realization
        
        Allowed fields: produced_qty, notes, status
        """
        realization = ProductionRealizationService.get_realization(realization_id)
        if not realization:
            raise ValueError(f"ProductionRealization {realization_id} not found")
        
        allowed_fields = {'produced_qty', 'notes', 'status'}
        for key, value in kwargs.items():
            if key in allowed_fields:
                setattr(realization, key, value)
        
        realization.updated_at = datetime.utcnow()
        db_session.commit()
        
        return realization
    
    @staticmethod
    def delete_realization(realization_id):
        """Delete a production realization"""
        realization = ProductionRealizationService.get_realization(realization_id)
        if not realization:
            raise ValueError(f"ProductionRealization {realization_id} not found")
        
        db_session.delete(realization)
        db_session.commit()
        
        return True
    
    @staticmethod
    def calculate_target_progress(target_id, tanggal=None):
        """
        Calculate total produced quantity and progress for a target
        
        Args:
            target_id: Production target ID
            tanggal: Optional date filter
            
        Returns:
            Dict with progress info:
            {
                'target_quantity': int,
                'total_produced': int,
                'remaining': int,
                'completion_percent': float,
                'status': str (pending|in_progress|completed|overproduced),
                'batch_count': int
            }
        """
        target = db_session.query(ProductionTarget).filter(
            ProductionTarget.id == target_id
        ).first()
        
        if not target:
            raise ValueError(f"ProductionTarget {target_id} not found")
        
        # Get realizations for this target
        realizations = ProductionRealizationService.list_realizations_for_target(target_id, tanggal)
        
        total_produced = sum(r.produced_qty for r in realizations)
        target_qty = target.target_quantity
        remaining = max(0, target_qty - total_produced)
        completion_percent = (total_produced / target_qty * 100) if target_qty > 0 else 0
        
        # Determine status
        if total_produced == 0:
            status = 'pending'
        elif total_produced >= target_qty:
            status = 'completed' if total_produced == target_qty else 'overproduced'
        else:
            status = 'in_progress'
        
        return {
            'target_quantity': target_qty,
            'total_produced': total_produced,
            'remaining': remaining,
            'completion_percent': round(completion_percent, 2),
            'status': status,
            'batch_count': len(realizations)
        }
    
    @staticmethod
    def get_plan_daily_progress(plan_id, tanggal=None):
        """
        Get aggregated progress for all targets in a daily plan
        
        Args:
            plan_id: Daily production plan ID
            tanggal: Optional date filter
            
        Returns:
            List of progress dicts per target
        """
        targets = db_session.query(ProductionTarget).filter(
            ProductionTarget.plan_id == plan_id
        ).all()
        
        progress_list = []
        for target in targets:
            progress = ProductionRealizationService.calculate_target_progress(target.id, tanggal)
            progress['target_id'] = target.id
            progress['product_name'] = target.product.name
            progress['unit_label'] = target.product.unit_label
            progress_list.append(progress)
        
        return progress_list
    
    @staticmethod
    def batch_realizations_as_json(realizations):
        """Convert list of realizations to JSON-serializable list"""
        result = []
        for r in realizations:
            result.append({
                'id': r.id,
                'target_id': r.target_id,
                'tanggal': r.tanggal.strftime('%Y-%m-%d') if r.tanggal else None,
                'batch_number': r.batch_number,
                'produced_qty': r.produced_qty,
                'notes': r.notes,
                'status': r.status,
                'created_by': r.created_by,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'product_name': r.target.product.name if r.target and r.target.product else None,
                'unit_label': r.target.product.unit_label if r.target and r.target.product else None
            })
        return result
