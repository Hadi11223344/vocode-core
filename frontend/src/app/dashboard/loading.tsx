export default function DashboardLoading() {
  return (
    <div className="space-y-6 animate-fade-in p-6">
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="dash-skeleton h-7 w-48 rounded-lg" />
          <div className="dash-skeleton h-4 w-64 rounded-lg" />
        </div>
        <div className="dash-skeleton h-9 w-28 rounded-lg" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="dash-skeleton h-28 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {[...Array(2)].map((_, i) => (
          <div key={i} className="dash-skeleton h-40 rounded-xl" />
        ))}
      </div>
    </div>
  );
}
