import React from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

// Each original page is served as-is inside an iframe. This intentionally
// preserves its HTML/CSS/JS rendering rather than recreating or redesigning it.
const pages = {
  '/': 'first.html',
  '/first': 'first.html',
  '/login': 'loginpage.html',
  '/register': 'register.html',
  '/forgot-password': 'forgetlogin.html',
  '/logout': 'logout.html',
  '/student': 'student.html',
  '/teacher': 'teacher-dashboard.html',
  '/attendance': 'att-pre.html',
  '/marks': 'mark-pre.html',
  '/career': 'career.html',
  '/student-recommendations': 'std-rec.html',
  '/student-profile': 'student-profile.html'
};

function OriginalPage() {
  const location = useLocation();
  const file = pages[location.pathname] || pages['/'];
  return <iframe title="StudentPath AI page" src={`/pages/${file}`} />;
}

export default function App() {
  return <Routes>
    <Route path="*" element={<OriginalPage />} />
  </Routes>;
}
