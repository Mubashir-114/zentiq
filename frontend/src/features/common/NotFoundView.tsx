import { Link } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { Home } from 'lucide-react';

export function NotFoundView() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
      <span className="text-6xl font-bold font-mono text-[#8B5CF6]">404</span>
      <h2 className="text-2xl font-bold text-[#F4F4F8]">Page Not Found</h2>
      <p className="text-sm text-[#9298AD] max-w-md">
        The requested module or resource does not exist in the current ZENTIQ milestone.
      </p>
      <Link to="/" className="pt-2">
        <Button variant="primary" leftIcon={<Home className="w-4 h-4" />}>
          Return to Overview
        </Button>
      </Link>
    </div>
  );
}

