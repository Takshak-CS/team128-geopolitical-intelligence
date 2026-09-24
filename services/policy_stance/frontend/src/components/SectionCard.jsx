import clsx from 'clsx';

export default function SectionCard({ title, kicker, className, children, actions }) {
  return (
    <section className={clsx('panel p-5 md:p-6', className)}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          {kicker ? <p className="text-xs uppercase tracking-[0.3em] text-steel">{kicker}</p> : null}
          <h2 className="font-display text-xl text-white md:text-2xl">{title}</h2>
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
